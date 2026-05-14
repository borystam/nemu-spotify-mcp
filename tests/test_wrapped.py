"""Tests for ``build_wrapped`` and the ``get_wrapped`` MCP tool.

The output shape is the contract: an MCP client (and the mimihagi
sub-agent in Phase 3) reads specific keys off it. The syrupy snapshot
test at the bottom locks the JSON shape so a refactor that changes a
field name fails loudly.

All tests run fully offline — the SpotifyClient fallback is mocked via
the same test-double pattern as the Phase 1 dispatch tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spotify_wrapped_mcp.wrapped import (
    build_wrapped,
    history_dir,
    monthly_history_path,
)

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


_FAKE_ARTIST = {
    "id": "0000000000000000000002",
    "name": "Lo-Fi Ghost",
    "uri": "spotify:artist:0000000000000000000002",
    "external_urls": {"spotify": "https://open.spotify.com/artist/0000000000000000000002"},
    "genres": ["lo-fi", "chillhop"],
}
_FAKE_ARTIST_B = {
    "id": "0000000000000000000005",
    "name": "Static Glow",
    "uri": "spotify:artist:0000000000000000000005",
    "external_urls": {"spotify": "https://open.spotify.com/artist/0000000000000000000005"},
    "genres": ["lo-fi"],
}
_FAKE_TRACK = {
    "id": "0000000000000000000001",
    "name": "Synth Wave",
    "uri": "spotify:track:0000000000000000000001",
    "external_urls": {"spotify": "https://open.spotify.com/track/0000000000000000000001"},
    "duration_ms": 180000,
    "artists": [_FAKE_ARTIST],
    "album": {
        "id": "0000000000000000000003",
        "name": "Static Cathedral",
        "uri": "spotify:album:0000000000000000000003",
    },
}
_FAKE_TRACK_B = {
    "id": "0000000000000000000006",
    "name": "Phantom Limb",
    "uri": "spotify:track:0000000000000000000006",
    "external_urls": {"spotify": "https://open.spotify.com/track/0000000000000000000006"},
    "duration_ms": 200000,
    "artists": [_FAKE_ARTIST_B],
    "album": {
        "id": "0000000000000000000007",
        "name": "Stations",
        "uri": "spotify:album:0000000000000000000007",
    },
}


class _StubSpotifyClient:
    """Stand-in for SpotifyClient used by the /me/top fallback path."""

    def __init__(self, top_artists: list[dict[str, Any]], top_tracks: list[dict[str, Any]]) -> None:
        self._top_artists = top_artists
        self._top_tracks = top_tracks

    def get_top(
        self,
        type_: str,
        *,
        time_range: str = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if type_ == "artists":
            return {"items": self._top_artists[:limit]}
        return {"items": self._top_tracks[:limit]}


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    return tmp_path / "history"


def _write_play(root: Path, track: dict[str, Any], played_at: datetime) -> None:
    path = monthly_history_path(played_at, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"track": track, "played_at": played_at.isoformat().replace("+00:00", "Z")})
        )
        fh.write("\n")


# ----------------------------------------------------------------------
# history_dir resolution
# ----------------------------------------------------------------------


class TestHistoryDir:
    def test_respects_explicit_env(self, tmp_path: Path) -> None:
        env = {"SPOTIFY_WRAPPED_MCP_HISTORY_DIR": str(tmp_path / "explicit")}
        assert history_dir(env=env) == tmp_path / "explicit"

    def test_uses_xdg_data_home(self, tmp_path: Path) -> None:
        env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
        assert history_dir(env=env) == tmp_path / "xdg" / "spotify-wrapped-mcp"

    def test_defaults_to_home_local_share(self) -> None:
        env: dict[str, str] = {}
        assert history_dir(env=env).as_posix().endswith(".local/share/spotify-wrapped-mcp")


# ----------------------------------------------------------------------
# build_wrapped from local jsonl
# ----------------------------------------------------------------------


class TestBuildFromLocal:
    def test_no_plays_falls_back_to_top(self, history_root: Path) -> None:
        client = _StubSpotifyClient(
            top_artists=[_FAKE_ARTIST],
            top_tracks=[_FAKE_TRACK],
        )
        out = build_wrapped(
            window="month",
            client=client,
            history_root=history_root,
        )
        assert out["source"] == "top_fallback"
        assert out["top_artists"][0]["uri"] == _FAKE_ARTIST["uri"]
        assert out["total_plays"] == 0
        assert out["daily_play_histogram"] == {}

    def test_uses_local_when_plays_present(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        # Three plays of the same track within the last week
        for offset_h in (1, 3, 25):
            _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=offset_h))
        client = _StubSpotifyClient(top_artists=[], top_tracks=[])
        out = build_wrapped(
            window="week",
            client=client,
            now=now,
            history_root=history_root,
        )
        assert out["source"] == "local"
        assert out["total_plays"] == 3
        assert out["unique_artists"] == 1
        assert out["top_artists"][0]["play_count"] == 3
        assert out["top_tracks"][0]["play_count"] == 3
        assert out["top_genres"][0]["genre"] in {"lo-fi", "chillhop"}

    def test_filters_plays_outside_window(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=2))  # in
        _write_play(history_root, _FAKE_TRACK, now - timedelta(days=14))  # out for week
        client = _StubSpotifyClient(top_artists=[], top_tracks=[])
        out = build_wrapped(
            window="week",
            client=client,
            now=now,
            history_root=history_root,
        )
        assert out["total_plays"] == 1

    def test_new_artists_excludes_previously_heard(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        # _FAKE_ARTIST heard months ago — not new
        _write_play(history_root, _FAKE_TRACK, now - timedelta(days=60))
        # _FAKE_ARTIST also heard this week → still not new
        _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=1))
        # _FAKE_ARTIST_B heard for the first time this week → new
        _write_play(history_root, _FAKE_TRACK_B, now - timedelta(hours=2))
        client = _StubSpotifyClient(top_artists=[], top_tracks=[])
        out = build_wrapped(
            window="week",
            client=client,
            now=now,
            history_root=history_root,
        )
        new_ids = {a["id"] for a in out["new_artists"]}
        assert _FAKE_ARTIST_B["id"] in new_ids
        assert _FAKE_ARTIST["id"] not in new_ids

    def test_histograms_populated(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=2))
        _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=4))
        client = _StubSpotifyClient(top_artists=[], top_tracks=[])
        out = build_wrapped(
            window="week",
            client=client,
            now=now,
            history_root=history_root,
        )
        # The two plays sit at hours 8 and 10 (12 - 4 and 12 - 2 in UTC)
        assert out["hour_of_day_histogram"]["8"] == 1
        assert out["hour_of_day_histogram"]["10"] == 1
        assert sum(out["daily_play_histogram"].values()) == 2

    def test_corrupt_jsonl_line_skipped(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
        _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=1))
        # Append a junk line directly
        path = monthly_history_path(now, root=history_root)
        path.open("a", encoding="utf-8").write("{not valid json\n")
        client = _StubSpotifyClient(top_artists=[], top_tracks=[])
        out = build_wrapped(
            window="week",
            client=client,
            now=now,
            history_root=history_root,
        )
        assert out["total_plays"] == 1


# ----------------------------------------------------------------------
# Output-shape snapshot (locks the contract)
# ----------------------------------------------------------------------


def test_wrapped_output_shape_snapshot(snapshot: Any, history_root: Path) -> None:
    """The shape of the wrapped JSON is a public contract. If this
    snapshot diff fires, you've changed the schema — coordinate with
    downstream consumers (mimihagi `mcp_mimihagi_music_digest`) before
    accepting the update.
    """
    now = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
    _write_play(history_root, _FAKE_TRACK, now - timedelta(hours=1))
    _write_play(history_root, _FAKE_TRACK_B, now - timedelta(hours=2))
    client = _StubSpotifyClient(top_artists=[], top_tracks=[])
    out = build_wrapped(
        window="week",
        client=client,
        now=now,
        history_root=history_root,
    )
    assert sorted(out.keys()) == snapshot


def test_wrapped_keys_stable() -> None:
    """A belt-and-braces check that doesn't require syrupy: every
    required key is present, regardless of source."""
    expected_keys = {
        "window",
        "from",
        "to",
        "source",
        "top_artists",
        "top_tracks",
        "top_genres",
        "total_plays",
        "unique_artists",
        "new_artists",
        "daily_play_histogram",
        "hour_of_day_histogram",
    }
    client = _StubSpotifyClient(top_artists=[], top_tracks=[])
    out = build_wrapped(window="month", client=client, history_root=Path("/nonexistent"))
    assert set(out.keys()) == expected_keys
