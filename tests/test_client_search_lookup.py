"""Unit tests for the search & lookup typed wrappers on SpotifyClient.

Every test runs against ``httpx.MockTransport`` — no real network calls.
The shape of the synthetic fixtures matches Spotify's documented JSON,
trimmed to the fields the tests actually assert on. Real personal data
never appears in this file (the fixtures use synthetic IDs and names
matching the Phase 0 ``alice_example`` / ``Synth Wave`` convention).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from spotify_wrapped_mcp.client import (
    MAX_IDS_PER_ALBUMS_LOOKUP,
    MAX_IDS_PER_ARTISTS_LOOKUP,
    MAX_IDS_PER_AUDIO_FEATURES_LOOKUP,
    MAX_IDS_PER_TRACKS_LOOKUP,
    SpotifyClient,
    SpotifyDeprecatedForNewAppsError,
)

_FAKE_TRACK = {
    "id": "0000000000000000000001",
    "name": "Synth Wave",
    "uri": "spotify:track:0000000000000000000001",
    "external_urls": {"spotify": "https://open.spotify.com/track/0000000000000000000001"},
    "href": "https://api.spotify.com/v1/tracks/0000000000000000000001",
    "duration_ms": 180000,
    "popularity": 42,
}
_FAKE_ARTIST = {
    "id": "0000000000000000000002",
    "name": "Lo-Fi Ghost",
    "uri": "spotify:artist:0000000000000000000002",
    "external_urls": {"spotify": "https://open.spotify.com/artist/0000000000000000000002"},
    "genres": ["lo-fi", "chillhop"],
    "followers": {"total": 1234},
}
_FAKE_ALBUM = {
    "id": "0000000000000000000003",
    "name": "Static Cathedral",
    "uri": "spotify:album:0000000000000000000003",
    "external_urls": {"spotify": "https://open.spotify.com/album/0000000000000000000003"},
    "tracks": {"items": [_FAKE_TRACK]},
}
_FAKE_PLAYLIST = {
    "id": "0000000000000000000004",
    "name": "Fixture Mix",
    "uri": "spotify:playlist:0000000000000000000004",
    "external_urls": {"spotify": "https://open.spotify.com/playlist/0000000000000000000004"},
    "tracks": {"items": [{"track": _FAKE_TRACK}]},
}


def _make_client(
    handler: callable,  # type: ignore[valid-type]
) -> SpotifyClient:
    """Build a SpotifyClient wired to a MockTransport with `handler`."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return SpotifyClient("fakeclientid0000000000000000000a", "fakerefresh", http=http)


def _token_response(req: httpx.Request) -> httpx.Response:
    """Stand-in token response. Re-used by every test below."""
    return httpx.Response(
        200,
        json={
            "access_token": "atok-test",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "user-top-read",
        },
    )


# ----------------------------------------------------------------------
# search
# ----------------------------------------------------------------------


class TestSearch:
    def _make(self, payload: dict[str, Any], *, capture: list[str] | None = None) -> SpotifyClient:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            if capture is not None:
                capture.append(str(req.url))
            return httpx.Response(200, json=payload)

        return _make_client(handler)

    def test_returns_grouped_results(self) -> None:
        body = {"tracks": {"items": [_FAKE_TRACK]}, "artists": {"items": [_FAKE_ARTIST]}}
        with self._make(body) as c:
            out = c.search("synth wave", ["track", "artist"])
        assert out["tracks"]["items"][0]["uri"].startswith("spotify:track:")

    def test_sends_comma_joined_types(self) -> None:
        captured: list[str] = []
        with self._make({"tracks": {"items": []}}, capture=captured) as c:
            c.search("ghost", ["track", "artist", "album"])
        qs = parse_qs(urlparse(captured[0]).query)
        assert qs["type"] == ["track,artist,album"]

    def test_forwards_limit_offset_market(self) -> None:
        captured: list[str] = []
        with self._make({}, capture=captured) as c:
            c.search("x", ["track"], limit=5, offset=20, market="PL")
        qs = parse_qs(urlparse(captured[0]).query)
        assert qs["limit"] == ["5"]
        assert qs["offset"] == ["20"]
        assert qs["market"] == ["PL"]

    def test_drops_none_params(self) -> None:
        captured: list[str] = []
        with self._make({}, capture=captured) as c:
            c.search("x", ["track"])
        qs = parse_qs(urlparse(captured[0]).query)
        assert "market" not in qs
        assert "include_external" not in qs

    def test_rejects_empty_types(self) -> None:
        with self._make({}) as c, pytest.raises(ValueError, match="at least one search type"):
            c.search("x", [])

    def test_empty_results_pass_through(self) -> None:
        with self._make({"tracks": {"items": []}}) as c:
            assert c.search("nothing", ["track"]) == {"tracks": {"items": []}}

    def test_propagates_4xx(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(400, json={"error": {"status": 400, "message": "bad q"}})

        with _make_client(handler) as c, pytest.raises(httpx.HTTPStatusError):
            c.search("x", ["track"])

    def test_propagates_429(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(
                429,
                json={"error": {"status": 429, "message": "rate limited"}},
                headers={"Retry-After": "1"},
            )

        with _make_client(handler) as c, pytest.raises(httpx.HTTPStatusError) as ei:
            c.search("x", ["track"])
        assert ei.value.response.status_code == 429
        assert ei.value.response.headers["Retry-After"] == "1"


# ----------------------------------------------------------------------
# single-id lookups (get_track / get_album / get_artist)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "args", "path_segment", "payload"),
    [
        ("get_track", ("0000000000000000000001",), "/tracks/", _FAKE_TRACK),
        ("get_album", ("0000000000000000000003",), "/albums/", _FAKE_ALBUM),
        ("get_artist", ("0000000000000000000002",), "/artists/", _FAKE_ARTIST),
        ("get_user_profile", ("alice_example",), "/users/", {"id": "alice_example"}),
        (
            "get_playlist",
            ("0000000000000000000004",),
            "/playlists/",
            _FAKE_PLAYLIST,
        ),
    ],
)
class TestSingleIdLookup:
    def _run(
        self,
        method: str,
        args: tuple[Any, ...],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json=payload)

        with _make_client(handler) as c:
            out = getattr(c, method)(*args)
        return out, captured

    def test_returns_payload(
        self,
        method: str,
        args: tuple[Any, ...],
        path_segment: str,
        payload: dict[str, Any],
    ) -> None:
        out, captured = self._run(method, args, payload)
        assert out == payload
        assert path_segment in captured[0]

    def test_propagates_404(
        self,
        method: str,
        args: tuple[Any, ...],
        path_segment: str,
        payload: dict[str, Any],
    ) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(404, json={"error": {"status": 404}})

        with _make_client(handler) as c, pytest.raises(httpx.HTTPStatusError):
            getattr(c, method)(*args)


# ----------------------------------------------------------------------
# bulk lookups (get_tracks / get_albums / get_artists / get_audio_features)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "limit", "endpoint"),
    [
        ("get_tracks", MAX_IDS_PER_TRACKS_LOOKUP, "/tracks"),
        ("get_albums", MAX_IDS_PER_ALBUMS_LOOKUP, "/albums"),
        ("get_artists", MAX_IDS_PER_ARTISTS_LOOKUP, "/artists"),
        (
            "get_audio_features",
            MAX_IDS_PER_AUDIO_FEATURES_LOOKUP,
            "/audio-features",
        ),
    ],
)
class TestBulkLookupCaps:
    def test_rejects_when_too_many_ids(self, method: str, limit: int, endpoint: str) -> None:
        with (
            _make_client(_token_response) as c,
            pytest.raises(ValueError, match="too many IDs"),
        ):
            getattr(c, method)([f"id{i:022d}" for i in range(limit + 1)])

    def test_rejects_when_empty(self, method: str, limit: int, endpoint: str) -> None:
        with (
            _make_client(_token_response) as c,
            pytest.raises(ValueError, match="at least one ID"),
        ):
            getattr(c, method)([])

    def test_rejects_id_with_embedded_comma(self, method: str, limit: int, endpoint: str) -> None:
        with (
            _make_client(_token_response) as c,
            pytest.raises(ValueError, match="invalid Spotify ID"),
        ):
            getattr(c, method)(["valid,bad"])

    def test_sends_comma_joined_ids(self, method: str, limit: int, endpoint: str) -> None:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json={"ok": True})

        with _make_client(handler) as c:
            getattr(c, method)(["alpha", "beta", "gamma"])
        qs = parse_qs(urlparse(captured[0]).query)
        assert qs["ids"] == ["alpha,beta,gamma"]
        assert endpoint in captured[0]


# ----------------------------------------------------------------------
# get_artist_top_tracks
# ----------------------------------------------------------------------


class TestArtistTopTracks:
    def test_returns_tracks_with_uri(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(200, json={"tracks": [_FAKE_TRACK]})

        with _make_client(handler) as c:
            out = c.get_artist_top_tracks("0000000000000000000002")
        assert out["tracks"][0]["uri"] == "spotify:track:0000000000000000000001"

    def test_market_omitted_when_not_passed(self) -> None:
        """``from_token`` was withdrawn for new apps on 2024-11-27 —
        omit the market param entirely when the caller doesn't pass
        one, so Spotify falls back to its global default rather than
        returning 403."""
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json={"tracks": []})

        with _make_client(handler) as c:
            c.get_artist_top_tracks("0000000000000000000002")
        assert "market" not in parse_qs(urlparse(captured[0]).query)

    def test_explicit_market_overrides_default(self) -> None:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json={"tracks": []})

        with _make_client(handler) as c:
            c.get_artist_top_tracks("0000000000000000000002", market="DE")
        assert parse_qs(urlparse(captured[0]).query)["market"] == ["DE"]


# ----------------------------------------------------------------------
# get_artist_albums (paginated)
# ----------------------------------------------------------------------


class TestArtistAlbums:
    def test_include_groups_joined(self) -> None:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json={"items": []})

        with _make_client(handler) as c:
            c.get_artist_albums(
                "0000000000000000000002",
                include_groups=["album", "single"],
                limit=10,
                offset=5,
            )
        qs = parse_qs(urlparse(captured[0]).query)
        assert qs["include_groups"] == ["album,single"]
        assert qs["limit"] == ["10"]
        assert qs["offset"] == ["5"]

    def test_omits_include_groups_when_none(self) -> None:
        captured: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            captured.append(str(req.url))
            return httpx.Response(200, json={"items": []})

        with _make_client(handler) as c:
            c.get_artist_albums("0000000000000000000002")
        assert "include_groups" not in parse_qs(urlparse(captured[0]).query)


# ----------------------------------------------------------------------
# Restricted-for-new-apps gate
# ----------------------------------------------------------------------


class TestDeprecatedForNewAppsGate:
    @pytest.mark.parametrize("status", [403, 404])
    def test_audio_features_raises_typed_error(self, status: int) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(status, json={"error": {"status": status}})

        with _make_client(handler) as c, pytest.raises(SpotifyDeprecatedForNewAppsError) as ei:
            c.get_audio_features(["0000000000000000000001"])
        assert "/audio-features" in str(ei.value)
        assert "2024-11-27" in str(ei.value)

    def test_audio_features_200_returns_payload(self) -> None:
        body = {"audio_features": [{"id": "0000000000000000000001", "tempo": 120.5}]}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(200, json=body)

        with _make_client(handler) as c:
            assert c.get_audio_features(["0000000000000000000001"]) == body

    def test_non_deprecated_endpoint_403_propagates_raw(self) -> None:
        """A 403 on a non-deprecated path must not be re-wrapped."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "accounts.spotify.com":
                return _token_response(req)
            return httpx.Response(403, json={"error": {"status": 403}})

        with _make_client(handler) as c, pytest.raises(httpx.HTTPStatusError):
            c.get_track("0000000000000000000001")
