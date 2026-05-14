"""Unit + property tests for spotify_wrapped_mcp.pkce."""

from __future__ import annotations

import base64
import hashlib
import re

from hypothesis import given
from hypothesis import strategies as st

from spotify_wrapped_mcp.pkce import challenge_from_verifier, generate_verifier

_BASE64URL_CHARSET = re.compile(r"[A-Za-z0-9_\-]+")


class TestGenerateVerifier:
    def test_charset_is_base64url(self) -> None:
        assert _BASE64URL_CHARSET.fullmatch(generate_verifier())

    def test_length_within_rfc7636_bounds(self) -> None:
        v = generate_verifier()
        assert 43 <= len(v) <= 128

    def test_default_length_is_86_chars(self) -> None:
        # 64 random bytes → 86-char base64url (no padding)
        assert len(generate_verifier()) == 86

    def test_each_call_is_unique(self) -> None:
        seen = {generate_verifier() for _ in range(64)}
        assert len(seen) == 64

    def test_no_padding(self) -> None:
        assert "=" not in generate_verifier()

    @given(st.integers(min_value=33, max_value=96))
    def test_respects_nbytes_argument(self, n: int) -> None:
        # ceil(n * 4 / 3) chars before stripping padding; ≥ 43 for n ≥ 33
        assert len(generate_verifier(nbytes=n)) >= 43


class TestChallengeFromVerifier:
    def test_matches_manual_sha256(self) -> None:
        v = "abcdefg"
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert challenge_from_verifier(v) == expected

    def test_is_43_chars(self) -> None:
        # SHA-256 → 32 bytes → 43 base64url chars unpadded
        assert len(challenge_from_verifier("anything")) == 43

    def test_no_padding(self) -> None:
        assert "=" not in challenge_from_verifier("anything")

    def test_charset_is_base64url(self) -> None:
        assert _BASE64URL_CHARSET.fullmatch(challenge_from_verifier("anything"))

    def test_different_verifier_gives_different_challenge(self) -> None:
        assert challenge_from_verifier("a") != challenge_from_verifier("b")

    @given(st.from_regex(r"^[A-Za-z0-9_\-]{43,128}$", fullmatch=True))
    def test_is_deterministic(self, s: str) -> None:
        assert challenge_from_verifier(s) == challenge_from_verifier(s)

    @given(st.from_regex(r"^[A-Za-z0-9_\-]{43,128}$", fullmatch=True))
    def test_output_shape_is_invariant(self, s: str) -> None:
        out = challenge_from_verifier(s)
        assert len(out) == 43
        assert _BASE64URL_CHARSET.fullmatch(out)
        assert "=" not in out
