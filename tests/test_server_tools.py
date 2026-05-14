"""Phase 1 MCP server tests.

Cover the tool descriptors (``list_tools`` returns the expected 22)
and the dispatch layer (``call_tool`` forwards each tool to the right
:class:`SpotifyClient` method, JSON-encodes the response, and unwraps
the deprecated-for-new-apps typed error to a structured payload).

The injected ``SpotifyClient`` is a thin spy that records the method
called and its arguments and returns a synthetic payload. No real HTTP
traffic; no real personal data.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from spotify_wrapped_mcp import server as srv
from spotify_wrapped_mcp.client import SpotifyDeprecatedForNewAppsError


class _SpyClient:
    """Records every typed-wrapper call. Returns ``self.payload`` from
    each one. Test-only stand-in for :class:`SpotifyClient`."""

    def __init__(self, payload: Any = None) -> None:
        self.payload: Any = payload if payload is not None else {"ok": True}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, args, kwargs))
        return self.payload

    # Tightly mirrors SpotifyClient's surface but returns self.payload.
    def search(self, *a: Any, **kw: Any) -> Any:
        return self._record("search", a, kw)

    def get_track(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_track", a, kw)

    def get_tracks(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_tracks", a, kw)

    def get_album(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_album", a, kw)

    def get_albums(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_albums", a, kw)

    def get_artist(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_artist", a, kw)

    def get_artists(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_artists", a, kw)

    def get_artist_top_tracks(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_artist_top_tracks", a, kw)

    def get_artist_albums(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_artist_albums", a, kw)

    def get_playlist(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_playlist", a, kw)

    def get_user_profile(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_user_profile", a, kw)

    def get_audio_features(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_audio_features", a, kw)

    def me(self) -> Any:
        return self._record("me", (), {})

    def get_top(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_top", a, kw)

    def get_recently_played(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_recently_played", a, kw)

    def get_now_playing(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_now_playing", a, kw)

    def get_playback_state(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_playback_state", a, kw)

    def get_devices(self) -> Any:
        return self._record("get_devices", (), {})

    def get_playlists(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_playlists", a, kw)

    def get_saved_tracks(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_saved_tracks", a, kw)

    def get_saved_albums(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_saved_albums", a, kw)

    def get_followed_artists(self, *a: Any, **kw: Any) -> Any:
        return self._record("get_followed_artists", a, kw)


@pytest.fixture
def spy() -> _SpyClient:
    spy = _SpyClient()
    srv._set_client_for_testing(spy)  # type: ignore[arg-type]
    yield spy
    srv._set_client_for_testing(None)


# ----------------------------------------------------------------------
# list_tools — every Phase 1 tool is registered with a valid descriptor
# ----------------------------------------------------------------------


_EXPECTED_TOOLS = {
    "search",
    "get_track",
    "get_tracks",
    "get_album",
    "get_albums",
    "get_artist",
    "get_artists",
    "get_artist_top_tracks",
    "get_artist_albums",
    "get_playlist",
    "get_user_profile",
    "get_audio_features",
    "get_me",
    "get_top",
    "get_recently_played",
    "get_now_playing",
    "get_playback_state",
    "get_devices",
    "get_playlists",
    "get_saved_tracks",
    "get_saved_albums",
    "get_followed_artists",
    "get_wrapped",
}


class TestListTools:
    def test_returns_every_phase_1_tool(self) -> None:
        names = set(srv._tool_names())
        assert names == _EXPECTED_TOOLS

    def test_count_is_23(self) -> None:
        assert len(list(srv._tool_names())) == 23

    def test_every_tool_has_schema_with_object_type(self) -> None:
        for tool in srv._TOOLS:
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    def test_every_tool_has_non_empty_description(self) -> None:
        for tool in srv._TOOLS:
            assert tool.description is not None
            assert len(tool.description.strip()) > 10

    def test_required_args_documented_where_present(self) -> None:
        """Tools that take IDs must declare them in `required`."""
        id_keyed = {
            "search": {"q", "types"},
            "get_track": {"track_id"},
            "get_tracks": {"ids"},
            "get_album": {"album_id"},
            "get_albums": {"ids"},
            "get_artist": {"artist_id"},
            "get_artists": {"ids"},
            "get_artist_top_tracks": {"artist_id"},
            "get_artist_albums": {"artist_id"},
            "get_playlist": {"playlist_id"},
            "get_user_profile": {"user_id"},
            "get_audio_features": {"ids"},
            "get_top": {"type"},
            "get_wrapped": {"window"},
        }
        for tool in srv._TOOLS:
            if tool.name in id_keyed:
                got = set(tool.inputSchema.get("required", []))
                assert got == id_keyed[tool.name], (tool.name, got)


# ----------------------------------------------------------------------
# call_tool dispatch — each tool maps to the matching client method
# ----------------------------------------------------------------------


def _call(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke the registered call_tool handler synchronously for tests."""
    return asyncio.run(srv.call_tool(name, arguments))


class TestDispatchSearchAndLookup:
    def test_search_passes_args(self, spy: _SpyClient) -> None:
        _call("search", {"q": "ghost", "types": ["track", "artist"], "limit": 5})
        m, _, kw = spy.calls[0]
        assert m == "search"
        assert kw == {
            "q": "ghost",
            "types": ["track", "artist"],
            "market": None,
            "limit": 5,
            "offset": 0,
            "include_external": None,
        }

    def test_get_track_passes_id(self, spy: _SpyClient) -> None:
        _call("get_track", {"track_id": "0000000000000000000001"})
        m, args, kw = spy.calls[0]
        assert m == "get_track"
        assert args == ("0000000000000000000001",)
        assert kw == {"market": None}

    def test_get_tracks_passes_id_list(self, spy: _SpyClient) -> None:
        _call("get_tracks", {"ids": ["a", "b"], "market": "PL"})
        m, args, kw = spy.calls[0]
        assert m == "get_tracks"
        assert args == (["a", "b"],)
        assert kw == {"market": "PL"}

    def test_get_artist_top_tracks_default_market(self, spy: _SpyClient) -> None:
        _call("get_artist_top_tracks", {"artist_id": "0000000000000000000002"})
        _, args, kw = spy.calls[0]
        assert args == ("0000000000000000000002",)
        assert kw == {"market": "from_token"}

    def test_get_artist_albums_with_include_groups(self, spy: _SpyClient) -> None:
        _call(
            "get_artist_albums",
            {
                "artist_id": "0000000000000000000002",
                "include_groups": ["album", "single"],
                "limit": 50,
                "offset": 0,
            },
        )
        _, _, kw = spy.calls[0]
        assert kw["include_groups"] == ["album", "single"]
        assert kw["limit"] == 50

    def test_get_playlist_fields_optional(self, spy: _SpyClient) -> None:
        _call(
            "get_playlist",
            {"playlist_id": "0000000000000000000004", "fields": "items(track(uri))"},
        )
        _, _, kw = spy.calls[0]
        assert kw["fields"] == "items(track(uri))"


class TestDispatchLibrary:
    def test_get_me_no_args(self, spy: _SpyClient) -> None:
        _call("get_me", {})
        assert spy.calls[0][0] == "me"

    def test_get_top_short_term(self, spy: _SpyClient) -> None:
        _call("get_top", {"type": "tracks", "time_range": "short_term", "limit": 10})
        _, args, kw = spy.calls[0]
        assert args == ("tracks",)
        assert kw == {"time_range": "short_term", "limit": 10, "offset": 0}

    def test_get_top_defaults(self, spy: _SpyClient) -> None:
        _call("get_top", {"type": "artists"})
        _, _, kw = spy.calls[0]
        assert kw["time_range"] == "medium_term"
        assert kw["limit"] == 20

    def test_get_recently_played_with_after(self, spy: _SpyClient) -> None:
        _call("get_recently_played", {"limit": 50, "after": 1715680800000})
        _, _, kw = spy.calls[0]
        assert kw == {"limit": 50, "before": None, "after": 1715680800000}

    def test_get_now_playing(self, spy: _SpyClient) -> None:
        _call("get_now_playing", {})
        assert spy.calls[0][0] == "get_now_playing"

    def test_get_playback_state(self, spy: _SpyClient) -> None:
        _call("get_playback_state", {"market": "PL"})
        _, _, kw = spy.calls[0]
        assert kw == {"market": "PL"}

    def test_get_devices(self, spy: _SpyClient) -> None:
        _call("get_devices", {})
        assert spy.calls[0][0] == "get_devices"

    def test_get_playlists(self, spy: _SpyClient) -> None:
        _call("get_playlists", {"limit": 50, "offset": 0})
        _, _, kw = spy.calls[0]
        assert kw == {"limit": 50, "offset": 0}

    def test_get_saved_tracks(self, spy: _SpyClient) -> None:
        _call("get_saved_tracks", {})
        _, _, kw = spy.calls[0]
        assert kw == {"limit": 20, "offset": 0, "market": None}

    def test_get_saved_albums(self, spy: _SpyClient) -> None:
        _call("get_saved_albums", {"market": "PL"})
        _, _, kw = spy.calls[0]
        assert kw == {"limit": 20, "offset": 0, "market": "PL"}

    def test_get_followed_artists_cursor(self, spy: _SpyClient) -> None:
        _call("get_followed_artists", {"after": "0000000000000000000002"})
        _, _, kw = spy.calls[0]
        assert kw == {"limit": 20, "after": "0000000000000000000002"}


# ----------------------------------------------------------------------
# Response shape — the dispatched payload is JSON-encoded as TextContent
# ----------------------------------------------------------------------


class TestCallToolResponseShape:
    def test_returns_single_text_content_with_json(self, spy: _SpyClient) -> None:
        spy.payload = {"items": [{"uri": "spotify:track:0000000000000000000001"}]}
        result = asyncio.run(srv.call_tool("get_top", {"type": "tracks"}))
        assert len(result) == 1
        assert result[0].type == "text"
        parsed = json.loads(result[0].text)
        assert parsed == spy.payload

    def test_unknown_tool_raises(self, spy: _SpyClient) -> None:
        with pytest.raises(ValueError, match="unknown tool"):
            asyncio.run(srv.call_tool("not_a_real_tool", {}))


# ----------------------------------------------------------------------
# Deprecated-for-new-apps error wrapping
# ----------------------------------------------------------------------


class _BoomSpotifyClient(_SpyClient):
    def get_audio_features(self, *a: Any, **kw: Any) -> Any:
        raise SpotifyDeprecatedForNewAppsError(
            "Spotify returned HTTP 403 for /audio-features. "
            "This endpoint was restricted to pre-2024-11-27 apps."
        )


class TestDeprecatedForNewAppsWrapping:
    def test_audio_features_returns_structured_error_payload(self) -> None:
        boom = _BoomSpotifyClient()
        srv._set_client_for_testing(boom)  # type: ignore[arg-type]
        try:
            result = asyncio.run(
                srv.call_tool("get_audio_features", {"ids": ["0000000000000000000001"]})
            )
        finally:
            srv._set_client_for_testing(None)
        parsed = json.loads(result[0].text)
        assert parsed["error"] == "deprecated_for_new_apps"
        assert parsed["tool"] == "get_audio_features"
        assert "2024-11-27" in parsed["message"]
