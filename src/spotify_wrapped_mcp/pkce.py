"""PKCE (RFC 7636) helpers — Proof Key for Code Exchange.

We use PKCE so we don't need a Spotify client secret — refresh tokens
don't expire unless the user revokes the app at
<https://www.spotify.com/account/apps/>.
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_verifier(nbytes: int = 64) -> str:
    """Return a fresh PKCE code_verifier.

    Per RFC 7636 §4.1, the verifier is 43-128 chars of ``[A-Z][a-z][0-9]-._~``.
    With ``nbytes=64`` (default) we get an 86-char base64url string — well
    inside the range and with ~512 bits of entropy.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def challenge_from_verifier(verifier: str) -> str:
    """Compute the S256 PKCE code_challenge from a verifier (RFC 7636 §4.2).

    Always returns 43 chars (SHA-256 → 32 bytes → 43-char unpadded base64url).
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
