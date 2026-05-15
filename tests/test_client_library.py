"""Unit tests for the library & listening typed wrappers.

These cover the user-scoped ``/me/...`` endpoints. As elsewhere, no
real network traffic; all responses fabricated to match the documented
Spotify shape, with synthetic IDs that match the Phase 0 placeholder
convention (``alice_example``, ``Synth Wave``, fake 22-char IDs).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from spotify_wrapped_mcp.client import SpotifyClient

_FAKE_ME = {
    "id": "alice_example",
    "display_name": "alice_example",
    "country": "PL",
    "product": "premium",
}
_FAKE_TRACK = {
    "id": "0000000000000000000001",
    "name": "Synth Wave",
    "uri": "spotify:track:0000000000000000000001",
    "external_urls": {"spotify": "https://open.spotify.com/track/0000000000000000000001"},
    "duration_ms": 180000,
}
_FAKE_ARTIST_ITEM = {
    "id": "0000000000000000000002",
    "name": "Lo-Fi Ghost",
    "uri": "spotify:artist:0000000000000000000002",
    "external_urls": {"spotify": "https://open.spotify.com/artist/0000000000000000000002"},
    "genres": ["lo-fi"],
}


def _token_response(req: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "atok-test",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "user-top-read user-read-recently-played",
        },
    )


def _client_for(handler: callable) -> SpotifyClient:  # type: ignore[valid-type]
    return SpotifyClient(
        "fakeclientid0000000000000000000a",
        "fakerefresh",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _captured_get(path: str, body: dict[str, Any] | int) -> tuple[SpotifyClient, list[str]]:
    """Make a client that returns ``body`` on any non-token GET and
    records the URLs in the returned list.

    If ``body`` is an int, treat it as a status code with empty body
    (so the test can simulate 204 No Content from ``/me/player/...``).
    """
    captured: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "accounts.spotify.com":
            return _token_response(req)
        captured.append(str(req.url))
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, json=body)

    return _client_for(handler), captured


# ----------------------------------------------------------------------
# get_top (artists / tracks)
# ----------------------------------------------------------------------


class TestGetTop:
    def test_artists_path(self) -> None:
        c, urls = _captured_get(
            "/me/top/artists",
            {"items": [_FAKE_ARTIST_ITEM]},
        )
        with c:
            out = c.get_top("artists")
        assert out["items"][0]["uri"] == "spotify:artist:0000000000000000000002"
        assert "/me/top/artists" in urls[0]

    def test_tracks_path(self) -> None:
        c, urls = _captured_get(
            "/me/top/tracks",
            {"items": [_FAKE_TRACK]},
        )
        with c:
            c.get_top("tracks")
        assert "/me/top/tracks" in urls[0]

    def test_default_time_range_medium_term(self) -> None:
        c, urls = _captured_get("/me/top/artists", {"items": []})
        with c:
            c.get_top("artists")
        assert parse_qs(urlparse(urls[0]).query)["time_range"] == ["medium_term"]

    def test_explicit_short_term(self) -> None:
        c, urls = _captured_get("/me/top/artists", {"items": []})
        with c:
            c.get_top("artists", time_range="short_term")
        assert parse_qs(urlparse(urls[0]).query)["time_range"] == ["short_term"]

    def test_long_term(self) -> None:
        c, urls = _captured_get("/me/top/tracks", {"items": []})
        with c:
            c.get_top("tracks", time_range="long_term", limit=50, offset=0)
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["time_range"] == ["long_term"]
        assert qs["limit"] == ["50"]


# ----------------------------------------------------------------------
# get_recently_played
# ----------------------------------------------------------------------


class TestRecentlyPlayed:
    def test_returns_items_with_played_at(self) -> None:
        body = {
            "items": [
                {
                    "track": _FAKE_TRACK,
                    "played_at": "2026-05-14T09:00:00Z",
                }
            ],
            "cursors": {"after": "1715680800000"},
        }
        c, _ = _captured_get("/me/player/recently-played", body)
        with c:
            assert c.get_recently_played()["items"][0]["played_at"].startswith("2026")

    def test_default_limit(self) -> None:
        c, urls = _captured_get("/me/player/recently-played", {"items": []})
        with c:
            c.get_recently_played()
        assert parse_qs(urlparse(urls[0]).query)["limit"] == ["20"]

    def test_cursor_after_propagated(self) -> None:
        c, urls = _captured_get("/me/player/recently-played", {"items": []})
        with c:
            c.get_recently_played(limit=50, after=1715680800000)
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["limit"] == ["50"]
        assert qs["after"] == ["1715680800000"]
        assert "before" not in qs

    def test_cursor_before_propagated(self) -> None:
        c, urls = _captured_get("/me/player/recently-played", {"items": []})
        with c:
            c.get_recently_played(before=1715680800000)
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["before"] == ["1715680800000"]
        assert "after" not in qs


# ----------------------------------------------------------------------
# get_now_playing + get_playback_state — 204 No Content handling
# ----------------------------------------------------------------------


class TestNowPlayingAndPlaybackState:
    def test_now_playing_returns_payload(self) -> None:
        body = {"item": _FAKE_TRACK, "is_playing": True}
        c, _ = _captured_get("/me/player/currently-playing", body)
        with c:
            assert c.get_now_playing() == body

    def test_now_playing_204_returns_empty_dict(self) -> None:
        c, _ = _captured_get("/me/player/currently-playing", 204)
        with c:
            assert c.get_now_playing() == {}

    def test_playback_state_204_returns_empty_dict(self) -> None:
        c, _ = _captured_get("/me/player", 204)
        with c:
            assert c.get_playback_state() == {}

    def test_now_playing_4xx_propagates(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(403, json={"error": {"status": 403, "message": "no premium"}})

        with _client_for(handler) as c, pytest.raises(httpx.HTTPStatusError) as ei:
            c.get_now_playing()
        assert ei.value.response.status_code == 403


# ----------------------------------------------------------------------
# get_devices
# ----------------------------------------------------------------------


class TestDevices:
    def test_returns_list_of_devices(self) -> None:
        body = {
            "devices": [
                {
                    "id": "device-loggia-0000000000000000000a",
                    "name": "Loggia",
                    "type": "Speaker",
                    "is_active": False,
                    "is_restricted": False,
                    "volume_percent": 50,
                }
            ]
        }
        c, _ = _captured_get("/me/player/devices", body)
        with c:
            out = c.get_devices()
        assert out["devices"][0]["name"] == "Loggia"


# ----------------------------------------------------------------------
# get_playlists / get_saved_tracks / get_saved_albums (paged)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get_playlists", "/me/playlists", {"items": [{"id": "0000000000000000000004"}]}),
        ("get_saved_tracks", "/me/tracks", {"items": [{"track": _FAKE_TRACK}]}),
        (
            "get_saved_albums",
            "/me/albums",
            {"items": [{"album": {"id": "0000000000000000000003"}}]},
        ),
    ],
)
class TestPagedLibrary:
    def test_default_pagination(self, method: str, path: str, body: dict[str, Any]) -> None:
        c, urls = _captured_get(path, body)
        with c:
            getattr(c, method)()
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["limit"] == ["20"]
        assert qs["offset"] == ["0"]

    def test_custom_pagination(self, method: str, path: str, body: dict[str, Any]) -> None:
        c, urls = _captured_get(path, body)
        with c:
            getattr(c, method)(limit=50, offset=100)
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["limit"] == ["50"]
        assert qs["offset"] == ["100"]

    def test_propagates_body(self, method: str, path: str, body: dict[str, Any]) -> None:
        c, _ = _captured_get(path, body)
        with c:
            assert getattr(c, method)() == body


# ----------------------------------------------------------------------
# get_followed_artists (cursor-paginated)
# ----------------------------------------------------------------------


class TestFollowedArtists:
    def test_default(self) -> None:
        c, urls = _captured_get(
            "/me/following",
            {"artists": {"items": [_FAKE_ARTIST_ITEM], "next": None}},
        )
        with c:
            out = c.get_followed_artists()
        assert out["artists"]["items"][0]["genres"] == ["lo-fi"]
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["type"] == ["artist"]
        assert qs["limit"] == ["20"]
        assert "after" not in qs

    def test_after_cursor_forwarded(self) -> None:
        c, urls = _captured_get("/me/following", {"artists": {"items": []}})
        with c:
            c.get_followed_artists(after="0000000000000000000002")
        qs = parse_qs(urlparse(urls[0]).query)
        assert qs["after"] == ["0000000000000000000002"]


# ----------------------------------------------------------------------
# /me — already covered in Phase 0 but smoke-check it returns alice_example
# ----------------------------------------------------------------------


def test_me_returns_profile() -> None:
    c, _ = _captured_get("/me", _FAKE_ME)
    with c:
        assert c.me() == _FAKE_ME
