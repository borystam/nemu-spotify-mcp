"""MCP stdio server entry point.

Phase 1 registers the read-only tool suite (search & lookup, library &
listening). Each tool maps directly to a single Spotify endpoint and
returns its JSON verbatim — preserving every ``uri`` and
``external_urls`` field so a downstream playback MCP (Sonos, generic
Spotify-Connect, etc.) can consume the result without a second lookup.

Phase 2 adds ``get_wrapped``, which aggregates over the local jsonl
written by :mod:`spotify_wrapped_mcp.cli.poller`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import __version__
from .client import SpotifyClient, SpotifyDeprecatedForNewAppsError
from .config import Credentials
from .wrapped import Window, build_wrapped

SERVER_NAME = "spotify-wrapped-mcp"

server: Server = Server(SERVER_NAME)

# ---------------------------------------------------------------------
# Tool descriptors
# ---------------------------------------------------------------------
#
# Every tool descriptor here corresponds to exactly one Spotify endpoint
# called by exactly one :class:`SpotifyClient` method. Keep this list
# and the dispatch table in :func:`_dispatch` in sync.

_STRING: dict[str, Any] = {"type": "string"}
_INTEGER: dict[str, Any] = {"type": "integer"}


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def _string_array(*, min_items: int = 1, max_items: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": _STRING,
        "minItems": min_items,
    }
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


_SEARCH_TYPES = ("track", "artist", "album", "playlist", "show", "episode", "audiobook")
_TIME_RANGES = ("short_term", "medium_term", "long_term")
_INCLUDE_GROUPS = ("album", "single", "appears_on", "compilation")

_TOOLS: list[Tool] = [
    # ---- search & lookup ------------------------------------------------
    Tool(
        name="search",
        description=(
            "Universal Spotify search. Returns matches grouped by type "
            "(tracks, artists, albums, playlists, etc.) with `uri` and "
            "`external_urls` on every item — feed those URIs into a "
            "playback MCP like sonos_play without a second lookup."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "q": {**_STRING, "description": "Search query."},
                "types": {
                    "type": "array",
                    "items": _enum(*_SEARCH_TYPES),
                    "minItems": 1,
                    "description": "Object types to search across.",
                },
                "market": {**_STRING, "description": "ISO-3166 country code. Optional."},
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
            },
            "required": ["q", "types"],
        },
    ),
    Tool(
        name="get_track",
        description="Track metadata (incl. ISRC, popularity, `uri`, `external_urls`).",
        inputSchema={
            "type": "object",
            "properties": {
                "track_id": _STRING,
                "market": _STRING,
            },
            "required": ["track_id"],
        },
    ),
    Tool(
        name="get_tracks",
        description="Bulk track lookup. Up to 50 IDs per call.",
        inputSchema={
            "type": "object",
            "properties": {
                "ids": _string_array(max_items=50),
                "market": _STRING,
            },
            "required": ["ids"],
        },
    ),
    Tool(
        name="get_album",
        description="Album metadata + tracklist. Each track carries `uri`.",
        inputSchema={
            "type": "object",
            "properties": {
                "album_id": _STRING,
                "market": _STRING,
            },
            "required": ["album_id"],
        },
    ),
    Tool(
        name="get_albums",
        description="Bulk album lookup. Up to 20 IDs per call.",
        inputSchema={
            "type": "object",
            "properties": {
                "ids": _string_array(max_items=20),
                "market": _STRING,
            },
            "required": ["ids"],
        },
    ),
    Tool(
        name="get_artist",
        description="Artist metadata: genres, popularity, follower count, `uri`.",
        inputSchema={
            "type": "object",
            "properties": {"artist_id": _STRING},
            "required": ["artist_id"],
        },
    ),
    Tool(
        name="get_artists",
        description="Bulk artist lookup. Up to 50 IDs per call.",
        inputSchema={
            "type": "object",
            "properties": {"ids": _string_array(max_items=50)},
            "required": ["ids"],
        },
    ),
    Tool(
        name="get_artist_top_tracks",
        description=(
            "Top tracks for an artist in the user's market. Useful for "
            "'play the top track from artist X' Sonos chains: pass the "
            "first item's `uri` straight into sonos_play."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "artist_id": _STRING,
                "market": {**_STRING, "default": "from_token"},
            },
            "required": ["artist_id"],
        },
    ),
    Tool(
        name="get_artist_albums",
        description="Paged discography. Filter with `include_groups`.",
        inputSchema={
            "type": "object",
            "properties": {
                "artist_id": _STRING,
                "include_groups": {
                    "type": "array",
                    "items": _enum(*_INCLUDE_GROUPS),
                },
                "market": _STRING,
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
            },
            "required": ["artist_id"],
        },
    ),
    Tool(
        name="get_playlist",
        description=(
            "Playlist metadata + tracks. Items carry track `uri` for " "downstream playback."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "playlist_id": _STRING,
                "market": _STRING,
                "fields": _STRING,
            },
            "required": ["playlist_id"],
        },
    ),
    Tool(
        name="get_user_profile",
        description="Public profile for any Spotify user.",
        inputSchema={
            "type": "object",
            "properties": {"user_id": _STRING},
            "required": ["user_id"],
        },
    ),
    Tool(
        name="get_audio_features",
        description=(
            "Bulk audio features (tempo, energy, danceability, etc.). Up "
            "to 100 IDs per call. **Restricted-for-new-apps** as of "
            "2024-11-27: apps created on or after that date will receive "
            "a clear error from this tool rather than silent failure."
        ),
        inputSchema={
            "type": "object",
            "properties": {"ids": _string_array(max_items=100)},
            "required": ["ids"],
        },
    ),
    # ---- library & listening -------------------------------------------
    Tool(
        name="get_me",
        description="The authenticated user's profile.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_top",
        description=(
            "Your top artists or tracks. Three time ranges (short / "
            "medium / long term ≈ 4 weeks / 6 months / lifetime). Items "
            "carry `uri` — pipe into a playback MCP for 'play my top "
            "track this week' chains."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": _enum("artists", "tracks"),
                "time_range": {**_enum(*_TIME_RANGES), "default": "medium_term"},
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
            },
            "required": ["type"],
        },
    ),
    Tool(
        name="get_recently_played",
        description=(
            "Your last ≤ 50 plays with timestamps. Used by the Phase 2 "
            "history poller; agents can also call directly for 'what did "
            "I just listen to' style questions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "before": {**_INTEGER, "description": "Epoch ms cursor."},
                "after": {**_INTEGER, "description": "Epoch ms cursor."},
            },
        },
    ),
    Tool(
        name="get_now_playing",
        description=(
            "Currently-playing track + device. Returns `{}` when "
            "nothing is playing (HTTP 204 from Spotify). Premium-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {"market": _STRING},
        },
    ),
    Tool(
        name="get_playback_state",
        description=(
            "Full playback state: active device, shuffle, repeat, "
            "current item. `{}` when no active device. Premium-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {"market": _STRING},
        },
    ),
    Tool(
        name="get_devices",
        description="Devices currently available to this Spotify account.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_playlists",
        description="Your playlists.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
            },
        },
    ),
    Tool(
        name="get_saved_tracks",
        description="Tracks you've saved/liked, paged, newest first.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
                "market": _STRING,
            },
        },
    ),
    Tool(
        name="get_saved_albums",
        description="Albums you've saved.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "offset": {**_INTEGER, "minimum": 0, "default": 0},
                "market": _STRING,
            },
        },
    ),
    Tool(
        name="get_followed_artists",
        description="Artists you follow. Cursor-paginated by artist ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {**_INTEGER, "minimum": 1, "maximum": 50, "default": 20},
                "after": {**_STRING, "description": "Cursor: artist ID to page after."},
            },
        },
    ),
    # ---- aggregations --------------------------------------------------
    Tool(
        name="get_wrapped",
        description=(
            "Structured month/week/year listening summary. Aggregates "
            "from the local jsonl written by `spotify-history-poller` "
            "when that file covers the window; otherwise falls back to "
            "`/me/top` (top_artists / top_tracks / top_genres still "
            "populated, histograms empty). Pure data shaping — no LLM. "
            "Stable shape: top_artists / top_tracks / top_genres / "
            "total_plays / unique_artists / new_artists / "
            "daily_play_histogram / hour_of_day_histogram. Each artist "
            "and track carries `uri` so an agent can pipe results "
            "straight into a playback MCP."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "window": _enum("week", "month", "year"),
            },
            "required": ["window"],
        },
    ),
]


@server.list_tools()  # type: ignore[no-untyped-call]
async def list_tools() -> list[Tool]:
    """Expose the registered MCP tools to the connected client."""
    return _TOOLS


# ---------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------

_client_singleton: SpotifyClient | None = None


def _get_client() -> SpotifyClient:
    """Lazy-construct the singleton :class:`SpotifyClient`.

    Tests inject via :func:`_set_client_for_testing`.
    """
    global _client_singleton  # noqa: PLW0603 — module-scoped singleton, by design
    if _client_singleton is None:
        creds = Credentials.load()
        _client_singleton = SpotifyClient(creds.client_id, creds.refresh_token)
    return _client_singleton


def _set_client_for_testing(client: SpotifyClient | None) -> None:
    """Test-only: replace the lazy singleton."""
    global _client_singleton  # noqa: PLW0603 — module-scoped singleton, by design
    _client_singleton = client


# Dispatch registry: tool name → adapter that maps the MCP arguments
# dict onto the matching ``SpotifyClient`` method. Centralising this
# keeps ``call_tool`` short (1 lookup + 1 call) and the per-tool
# argument shapes obvious at a glance.
_Dispatcher = "Callable[[SpotifyClient, dict[str, Any]], dict[str, Any]]"


def _build_handlers() -> dict[str, Any]:
    return {
        # ---- search & lookup ----------------------------------------
        "search": lambda c, a: c.search(
            q=a["q"],
            types=a["types"],
            market=a.get("market"),
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
            include_external=a.get("include_external"),
        ),
        "get_track": lambda c, a: c.get_track(a["track_id"], market=a.get("market")),
        "get_tracks": lambda c, a: c.get_tracks(a["ids"], market=a.get("market")),
        "get_album": lambda c, a: c.get_album(a["album_id"], market=a.get("market")),
        "get_albums": lambda c, a: c.get_albums(a["ids"], market=a.get("market")),
        "get_artist": lambda c, a: c.get_artist(a["artist_id"]),
        "get_artists": lambda c, a: c.get_artists(a["ids"]),
        "get_artist_top_tracks": lambda c, a: c.get_artist_top_tracks(
            a["artist_id"], market=a.get("market", "from_token")
        ),
        "get_artist_albums": lambda c, a: c.get_artist_albums(
            a["artist_id"],
            include_groups=a.get("include_groups"),
            market=a.get("market"),
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
        ),
        "get_playlist": lambda c, a: c.get_playlist(
            a["playlist_id"],
            market=a.get("market"),
            fields=a.get("fields"),
        ),
        "get_user_profile": lambda c, a: c.get_user_profile(a["user_id"]),
        "get_audio_features": lambda c, a: c.get_audio_features(a["ids"]),
        # ---- library & listening ------------------------------------
        "get_me": lambda c, _a: c.me(),
        "get_top": lambda c, a: c.get_top(
            a["type"],
            time_range=a.get("time_range", "medium_term"),
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
        ),
        "get_recently_played": lambda c, a: c.get_recently_played(
            limit=a.get("limit", 20),
            before=a.get("before"),
            after=a.get("after"),
        ),
        "get_now_playing": lambda c, a: c.get_now_playing(market=a.get("market")),
        "get_playback_state": lambda c, a: c.get_playback_state(market=a.get("market")),
        "get_devices": lambda c, _a: c.get_devices(),
        "get_playlists": lambda c, a: c.get_playlists(
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
        ),
        "get_saved_tracks": lambda c, a: c.get_saved_tracks(
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
            market=a.get("market"),
        ),
        "get_saved_albums": lambda c, a: c.get_saved_albums(
            limit=a.get("limit", 20),
            offset=a.get("offset", 0),
            market=a.get("market"),
        ),
        "get_followed_artists": lambda c, a: c.get_followed_artists(
            limit=a.get("limit", 20),
            after=a.get("after"),
        ),
        # ---- aggregations -------------------------------------------
        "get_wrapped": lambda c, a: build_wrapped(
            window=_validated_window(a["window"]),
            client=c,
        ),
    }


def _validated_window(value: str) -> Window:
    if value not in ("week", "month", "year"):
        raise ValueError(f"window must be week|month|year, got {value!r}")
    return value  # type: ignore[return-value]


_HANDLERS: dict[str, Any] = _build_handlers()


def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")
    result: dict[str, Any] = handler(_get_client(), arguments)
    return result


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool call to the matching :class:`SpotifyClient` method.

    Returns a single :class:`TextContent` block carrying the JSON-encoded
    response. The 'restricted-for-new-apps' typed error is unwrapped to
    a structured payload so agents can explain it to users.
    """
    try:
        payload = await asyncio.to_thread(_dispatch, name, arguments)
    except SpotifyDeprecatedForNewAppsError as exc:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "deprecated_for_new_apps",
                        "tool": name,
                        "message": str(exc),
                    }
                ),
            )
        ]
    return [
        TextContent(
            type="text",
            text=json.dumps(payload),
        )
    ]


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> int:
    """Block on the stdio server until the client disconnects. Returns 0."""
    asyncio.run(_serve())
    return 0


def _tool_names() -> Iterable[str]:
    """Stable iteration order over registered tool names; used by tests."""
    return (t.name for t in _TOOLS)


__all__ = [
    "SERVER_NAME",
    "__version__",
    "_set_client_for_testing",
    "_tool_names",
    "call_tool",
    "list_tools",
    "main",
    "server",
]
