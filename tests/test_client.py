"""Unit tests for spotify_wrapped_mcp.client.SpotifyClient."""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

import httpx
import pytest

from spotify_wrapped_mcp.client import SpotifyClient


def _transport(
    *,
    token_calls: list[dict[str, str]] | None = None,
    me_payload: dict[str, Any] | None = None,
    rotate_refresh: bool = False,
    me_status: int = 200,
    token_status: int = 200,
) -> httpx.MockTransport:
    counter = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "accounts.spotify.com":
            counter["n"] += 1
            body: dict[str, Any] = {
                "access_token": f"atok{counter['n']}",
                "expires_in": 3600,
                "scope": "user-top-read",
                "token_type": "Bearer",
            }
            if rotate_refresh:
                body["refresh_token"] = f"newrt{counter['n']}"
            if token_calls is not None:
                token_calls.append(dict(urllib.parse.parse_qsl(req.content.decode())))
            return httpx.Response(token_status, json=body)
        if req.url.path == "/v1/me":
            return httpx.Response(me_status, json=me_payload or {"id": "alice_example"})
        raise AssertionError(f"unexpected request: {req.url}")

    return httpx.MockTransport(handler)


class TestSpotifyClientMe:
    def test_returns_profile_dict(self) -> None:
        http = httpx.Client(
            transport=_transport(
                me_payload={
                    "display_name": "alice_example",
                    "id": "alice_example",
                    "product": "premium",
                    "country": "PL",
                }
            )
        )
        with SpotifyClient("cid", "rtok", http=http) as c:
            profile = c.me()
        assert profile["display_name"] == "alice_example"
        assert profile["product"] == "premium"
        assert profile["country"] == "PL"

    def test_sends_bearer_authorization_header(self) -> None:
        seen: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "the_atok",
                        "expires_in": 3600,
                        "scope": "x",
                        "token_type": "Bearer",
                    },
                )
            seen.append(req.headers.get("Authorization", ""))
            return httpx.Response(200, json={})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        with SpotifyClient("cid", "rtok", http=http) as c:
            c.me()
        assert seen == ["Bearer the_atok"]

    def test_get_with_query_params(self) -> None:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "a",
                        "expires_in": 3600,
                        "scope": "x",
                        "token_type": "Bearer",
                    },
                )
            captured.append(str(req.url))
            return httpx.Response(200, json={"items": []})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        with SpotifyClient("cid", "rtok", http=http) as c:
            c.get("/me/top/artists", params={"limit": 5, "time_range": "short_term"})
        assert "limit=5" in captured[0]
        assert "time_range=short_term" in captured[0]


class TestSpotifyClientRefresh:
    def test_refreshes_once_then_caches_for_subsequent_calls(self) -> None:
        token_calls: list[dict[str, str]] = []
        http = httpx.Client(transport=_transport(token_calls=token_calls))
        with SpotifyClient("cid", "rtok", http=http) as c:
            c.me()
            c.me()
            c.me()
        assert len(token_calls) == 1
        assert token_calls[0]["grant_type"] == "refresh_token"
        assert token_calls[0]["refresh_token"] == "rtok"
        assert token_calls[0]["client_id"] == "cid"

    def test_refreshes_again_when_token_expires(self) -> None:
        token_calls: list[dict[str, str]] = []
        http = httpx.Client(transport=_transport(token_calls=token_calls))
        with SpotifyClient("cid", "rtok", http=http) as c:
            c.me()
            assert c._access is not None
            c._access.expires_at = time.time() - 1
            c.me()
        assert len(token_calls) == 2

    def test_rotates_refresh_token_when_server_returns_new_one(self) -> None:
        http = httpx.Client(transport=_transport(rotate_refresh=True))
        with SpotifyClient("cid", "oldrt", http=http) as c:
            c.me()
            assert c.refresh_token.startswith("newrt")

    def test_keeps_refresh_token_when_server_does_not_rotate(self) -> None:
        http = httpx.Client(transport=_transport(rotate_refresh=False))
        with SpotifyClient("cid", "oldrt", http=http) as c:
            c.me()
            assert c.refresh_token == "oldrt"


class TestSpotifyClientErrors:
    def test_raises_on_4xx_from_api(self) -> None:
        http = httpx.Client(transport=_transport(me_status=401))
        with (
            SpotifyClient("cid", "rtok", http=http) as c,
            pytest.raises(httpx.HTTPStatusError) as excinfo,
        ):
            c.me()
        assert excinfo.value.response.status_code == 401

    def test_raises_on_refresh_failure(self) -> None:
        http = httpx.Client(transport=_transport(token_status=400))
        with (
            SpotifyClient("cid", "expiredrt", http=http) as c,
            pytest.raises(httpx.HTTPStatusError),
        ):
            c.me()


class TestSpotifyClientLifecycle:
    def test_does_not_close_externally_provided_http_client(self) -> None:
        http = httpx.Client(transport=_transport())
        with SpotifyClient("cid", "rtok", http=http) as c:
            c.me()
        assert not http.is_closed
        http.close()

    def test_closes_internally_owned_http_client_on_close(self) -> None:
        c = SpotifyClient("cid", "rtok")
        owned = c._http
        c.close()
        assert owned.is_closed
