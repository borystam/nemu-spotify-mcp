"""Tests for the ``spotify-history-poller`` CLI.

The poller reads ``/me/player/recently-played`` and appends new plays
to ``history-YYYY-MM.jsonl``, deduping by ``played_at``. Tests run
fully offline by injecting a stub SpotifyClient that returns canned
payloads.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spotify_wrapped_mcp.cli.poller import _run_once
from spotify_wrapped_mcp.wrapped import monthly_history_path

_FAKE_ARTIST = {
    "id": "0000000000000000000002",
    "name": "Lo-Fi Ghost",
    "uri": "spotify:artist:0000000000000000000002",
    "external_urls": {"spotify": "https://open.spotify.com/artist/0000000000000000000002"},
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _StubClient:
    """Returns a fixed recently-played payload."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def get_recently_played(self, *, limit: int = 50, **_kw: Any) -> dict[str, Any]:
        assert limit == 50
        return {"items": self._items}


def _items(*plays: tuple[dict[str, Any], datetime]) -> list[dict[str, Any]]:
    return [{"track": tr, "played_at": _iso(t)} for tr, t in plays]


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    return tmp_path / "history"


# ----------------------------------------------------------------------


class TestRunOnce:
    def test_appends_new_plays(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
        client = _StubClient(
            _items((_FAKE_TRACK, now - timedelta(minutes=10))),
        )
        appended = _run_once(client, history_root)
        assert appended == 1
        path = monthly_history_path(now, root=history_root)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["track"]["id"] == _FAKE_TRACK["id"]
        assert rec["played_at"].endswith("Z")

    def test_deduplicates_against_existing(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
        first = _items(
            (_FAKE_TRACK, now - timedelta(minutes=30)),
            (_FAKE_TRACK, now - timedelta(minutes=10)),
        )
        client = _StubClient(first)
        _run_once(client, history_root)
        # Run again: same items returned by Spotify, expect zero new
        appended = _run_once(client, history_root)
        assert appended == 0
        path = monthly_history_path(now, root=history_root)
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    def test_appends_only_the_new_play(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
        # First poll: 2 plays
        _run_once(
            _StubClient(
                _items(
                    (_FAKE_TRACK, now - timedelta(minutes=30)),
                    (_FAKE_TRACK, now - timedelta(minutes=20)),
                )
            ),
            history_root,
        )
        # Second poll: same first 2, plus 1 new
        appended = _run_once(
            _StubClient(
                _items(
                    (_FAKE_TRACK, now - timedelta(minutes=30)),
                    (_FAKE_TRACK, now - timedelta(minutes=20)),
                    (_FAKE_TRACK, now - timedelta(minutes=5)),
                )
            ),
            history_root,
        )
        assert appended == 1
        path = monthly_history_path(now, root=history_root)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3

    def test_splits_plays_across_month_boundary(self, history_root: Path) -> None:
        # One play on April 30, one on May 1
        apr_30 = datetime(2026, 4, 30, 23, 30, tzinfo=timezone.utc)
        may_1 = datetime(2026, 5, 1, 0, 15, tzinfo=timezone.utc)
        client = _StubClient(_items((_FAKE_TRACK, apr_30), (_FAKE_TRACK, may_1)))
        _run_once(client, history_root)
        april_path = monthly_history_path(apr_30, root=history_root)
        may_path = monthly_history_path(may_1, root=history_root)
        assert april_path.exists()
        assert may_path.exists()
        assert len(april_path.read_text(encoding="utf-8").splitlines()) == 1
        assert len(may_path.read_text(encoding="utf-8").splitlines()) == 1

    def test_handles_empty_response(self, history_root: Path) -> None:
        client = _StubClient([])
        appended = _run_once(client, history_root)
        assert appended == 0
        # No files created
        assert not history_root.exists() or not any(history_root.iterdir())

    def test_skips_items_without_track(self, history_root: Path) -> None:
        now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
        client = _StubClient(
            [
                {"track": None, "played_at": _iso(now - timedelta(minutes=5))},
                {"track": _FAKE_TRACK, "played_at": _iso(now - timedelta(minutes=10))},
            ]
        )
        appended = _run_once(client, history_root)
        assert appended == 1

    def test_skips_items_without_played_at(self, history_root: Path) -> None:
        client = _StubClient(
            [{"track": _FAKE_TRACK}],  # no played_at
        )
        appended = _run_once(client, history_root)
        assert appended == 0
