"""Unit tests for spotify_wrapped_mcp.auth — OAuth helpers."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import httpx
import pytest

from spotify_wrapped_mcp import auth as auth_mod
from spotify_wrapped_mcp.auth import (
    AUTHORIZE_URL,
    DEFAULT_REDIRECT_URI,
    SCOPES,
    TOKEN_URL,
    TokenResponse,
    build_authorize_url,
    exchange_code,
    run_pkce_flow,
)

from .conftest import free_port

# ---------- build_authorize_url ----------------------------------------------


class TestBuildAuthorizeUrl:
    def _parse(self, **overrides: Any) -> dict[str, list[str]]:
        kwargs: dict[str, Any] = {
            "client_id": "cid",
            "redirect_uri": DEFAULT_REDIRECT_URI,
            "code_challenge": "chal",
            "state": "stateX",
        }
        kwargs.update(overrides)
        url = build_authorize_url(**kwargs)
        parsed = urllib.parse.urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
        return urllib.parse.parse_qs(parsed.query)

    def test_includes_required_oauth_params(self) -> None:
        qs = self._parse()
        assert qs["client_id"] == ["cid"]
        assert qs["response_type"] == ["code"]
        assert qs["redirect_uri"] == [DEFAULT_REDIRECT_URI]
        assert qs["code_challenge_method"] == ["S256"]
        assert qs["code_challenge"] == ["chal"]
        assert qs["state"] == ["stateX"]

    def test_includes_every_default_scope(self) -> None:
        granted = self._parse()["scope"][0].split()
        for scope in SCOPES:
            assert scope in granted
        assert len(granted) == len(SCOPES)

    def test_default_redirect_uri_uses_loopback_ip_not_localhost(self) -> None:
        # Spotify is strict about loopback-IP vs `localhost`.
        assert "127.0.0.1" in DEFAULT_REDIRECT_URI
        assert "localhost" not in DEFAULT_REDIRECT_URI

    def test_omits_client_secret(self) -> None:
        url = build_authorize_url(
            client_id="cid",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_challenge="chal",
            state="s",
        )
        assert "client_secret" not in url

    def test_custom_scopes_argument(self) -> None:
        qs = self._parse(scopes=("user-top-read",))
        assert qs["scope"] == ["user-top-read"]

    def test_url_query_is_form_urlencoded_not_fragment(self) -> None:
        url = build_authorize_url(
            client_id="c",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_challenge="x",
            state="s",
        )
        parsed = urllib.parse.urlparse(url)
        assert parsed.query  # there is a query string
        assert not parsed.fragment


# ---------- exchange_code -----------------------------------------------------


def _token_transport(
    capture: dict[str, str] | None = None,
    response: dict[str, Any] | None = None,
    status: int = 200,
) -> httpx.MockTransport:
    body = response or {
        "access_token": "atok",
        "refresh_token": "rtok",
        "expires_in": 3600,
        "scope": " ".join(SCOPES),
        "token_type": "Bearer",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["url"] = str(req.url)
            capture["content"] = req.content.decode()
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


class TestExchangeCode:
    def test_returns_parsed_token_response(self) -> None:
        c = httpx.Client(transport=_token_transport())
        r = exchange_code(
            client_id="cid",
            code="thecode",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_verifier="v",
            client=c,
        )
        assert isinstance(r, TokenResponse)
        assert r.access_token == "atok"
        assert r.refresh_token == "rtok"
        assert r.expires_in == 3600
        assert r.token_type == "Bearer"
        assert r.scope == " ".join(SCOPES)

    def test_posts_to_spotify_token_endpoint(self) -> None:
        cap: dict[str, str] = {}
        c = httpx.Client(transport=_token_transport(cap))
        exchange_code(
            client_id="cid",
            code="thecode",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_verifier="v",
            client=c,
        )
        assert cap["url"] == TOKEN_URL

    def test_body_uses_pkce_verifier_and_omits_secret(self) -> None:
        cap: dict[str, str] = {}
        c = httpx.Client(transport=_token_transport(cap))
        exchange_code(
            client_id="cid",
            code="thecode",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_verifier="my_verifier_value",
            client=c,
        )
        body = dict(urllib.parse.parse_qsl(cap["content"]))
        assert body == {
            "grant_type": "authorization_code",
            "code": "thecode",
            "redirect_uri": DEFAULT_REDIRECT_URI,
            "client_id": "cid",
            "code_verifier": "my_verifier_value",
        }
        assert "client_secret" not in body

    def test_4xx_response_raises_httpstatuserror(self) -> None:
        c = httpx.Client(
            transport=_token_transport(response={"error": "invalid_grant"}, status=400)
        )
        with pytest.raises(httpx.HTTPStatusError):
            exchange_code(
                client_id="cid",
                code="bad",
                redirect_uri=DEFAULT_REDIRECT_URI,
                code_verifier="v",
                client=c,
            )

    def test_uses_caller_provided_client(self) -> None:
        # When client= is passed, exchange_code must not close it.
        c = httpx.Client(transport=_token_transport())
        exchange_code(
            client_id="cid",
            code="c",
            redirect_uri=DEFAULT_REDIRECT_URI,
            code_verifier="v",
            client=c,
        )
        assert not c.is_closed
        c.close()


# ---------- run_pkce_flow (with mocked browser + token endpoint) -------------


def _patch_exchange(monkeypatch: pytest.MonkeyPatch, response: TokenResponse) -> None:
    def fake_exchange(**_kw: Any) -> TokenResponse:
        return response

    monkeypatch.setattr(auth_mod, "exchange_code", fake_exchange)


def _patch_browser_to_hit_callback(
    monkeypatch: pytest.MonkeyPatch, *, error: str | None = None, bad_state: bool = False
) -> None:
    def fake_browser(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        state = qs["state"][0]
        redirect = qs["redirect_uri"][0]
        if error:
            cb = f"{redirect}?error={error}&state={urllib.parse.quote(state)}"
        elif bad_state:
            cb = f"{redirect}?code=fakecode&state=wrongstate"
        else:
            cb = f"{redirect}?code=fakecode&state={urllib.parse.quote(state)}"
        # The handler returns 400 on errors; urllib raises HTTPError on 4xx.
        # That's fine — we only care that the callback was reached and the
        # server-side state was recorded.
        try:
            with urllib.request.urlopen(cb, timeout=5) as r:
                r.read()
        except urllib.error.HTTPError:
            pass
        return True

    monkeypatch.setattr(auth_mod.webbrowser, "open", fake_browser)


class TestRunPkceFlow:
    def test_happy_path_returns_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_exchange(
            monkeypatch,
            TokenResponse(
                access_token="atok",
                refresh_token="rtok",
                expires_in=3600,
                scope=" ".join(SCOPES),
                token_type="Bearer",
            ),
        )
        _patch_browser_to_hit_callback(monkeypatch)
        port = free_port()
        tokens = run_pkce_flow(
            "cid",
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            timeout_seconds=10.0,
        )
        assert tokens.access_token == "atok"
        assert tokens.refresh_token == "rtok"

    def test_error_in_callback_raises_runtimeerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_browser_to_hit_callback(monkeypatch, error="access_denied")
        port = free_port()
        with pytest.raises(RuntimeError, match="access_denied"):
            run_pkce_flow(
                "cid",
                redirect_uri=f"http://127.0.0.1:{port}/callback",
                timeout_seconds=10.0,
            )

    def test_state_mismatch_raises_runtimeerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_browser_to_hit_callback(monkeypatch, bad_state=True)
        port = free_port()
        with pytest.raises(RuntimeError, match="state_mismatch"):
            run_pkce_flow(
                "cid",
                redirect_uri=f"http://127.0.0.1:{port}/callback",
                timeout_seconds=10.0,
            )

    def test_timeout_raises_timeouterror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # webbrowser.open is patched to do nothing → callback never fires.
        monkeypatch.setattr(auth_mod.webbrowser, "open", lambda _u: False)
        port = free_port()
        with pytest.raises(TimeoutError):
            run_pkce_flow(
                "cid",
                redirect_uri=f"http://127.0.0.1:{port}/callback",
                timeout_seconds=0.2,
            )

    def test_no_browser_skips_webbrowser_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(auth_mod.webbrowser, "open", lambda u: calls.append(u) or True)
        port = free_port()
        with pytest.raises(TimeoutError):
            run_pkce_flow(
                "cid",
                redirect_uri=f"http://127.0.0.1:{port}/callback",
                timeout_seconds=0.2,
                open_browser=False,
            )
        assert calls == [], "open_browser=False must not call webbrowser.open"

    def test_notify_callback_is_invoked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_exchange(
            monkeypatch,
            TokenResponse(
                access_token="atok",
                refresh_token="rtok",
                expires_in=3600,
                scope="x",
                token_type="Bearer",
            ),
        )
        _patch_browser_to_hit_callback(monkeypatch)
        messages: list[str] = []
        port = free_port()
        run_pkce_flow(
            "cid",
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            timeout_seconds=10.0,
            notify=messages.append,
        )
        assert any("Open this URL" in m for m in messages)
        assert any("Waiting for callback" in m for m in messages)
