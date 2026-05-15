"""``get_wrapped`` aggregation logic.

Pure data shaping over the local history written by
:mod:`spotify_wrapped_mcp.cli.poller`, with a graceful fallback to
Spotify's ``/me/top`` when no local history covers the requested
window. No LLM calls — the caller is responsible for turning the
structured output into narrative prose.

The output shape is locked by a syrupy snapshot test
(``tests/test_wrapped.py``); refactors must keep it stable.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from .client import SpotifyClient

Window = Literal["week", "month", "year"]

HISTORY_DIR_ENV = "SPOTIFY_WRAPPED_MCP_HISTORY_DIR"
DEFAULT_HISTORY_SUBDIR = Path(".local") / "share" / "spotify-wrapped-mcp"

_WINDOW_DELTA: dict[Window, timedelta] = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}

_TopTimeRange = Literal["short_term", "medium_term", "long_term"]

# Spotify's /me/top time_range buckets, ordered from finest to coarsest.
_TIME_RANGE_FOR_WINDOW: dict[Window, _TopTimeRange] = {
    "week": "short_term",  # ~4 weeks
    "month": "short_term",  # ~4 weeks — the finest bucket Spotify offers
    "year": "long_term",  # lifetime; we round up
}


# ----------------------------------------------------------------------
# History storage paths
# ----------------------------------------------------------------------


def history_dir(env: dict[str, str] | None = None) -> Path:
    """Return the directory where the poller writes monthly jsonl files.

    Order of precedence:
      1. ``$SPOTIFY_WRAPPED_MCP_HISTORY_DIR`` if set
      2. ``$XDG_DATA_HOME/spotify-wrapped-mcp``
      3. ``~/.local/share/spotify-wrapped-mcp``
    """
    import os

    e = env if env is not None else dict(os.environ)
    override = e.get(HISTORY_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = e.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "spotify-wrapped-mcp"
    return Path.home() / DEFAULT_HISTORY_SUBDIR


def monthly_history_path(month: datetime, root: Path | None = None) -> Path:
    """Return the jsonl path for the month containing ``month``."""
    base = root if root is not None else history_dir()
    return base / f"history-{month.strftime('%Y-%m')}.jsonl"


# ----------------------------------------------------------------------
# Reading the local jsonl
# ----------------------------------------------------------------------


class Play(TypedDict, total=False):
    track: dict[str, Any]
    played_at: str  # ISO-8601


def _iter_plays_for_range(
    start: datetime,
    end: datetime,
    root: Path | None = None,
) -> Iterator[Play]:
    """Yield every play whose ``played_at`` falls within ``[start, end)``.

    Scans every monthly jsonl that could overlap the range. Plays
    outside the range are skipped quietly so callers don't have to
    re-filter.
    """
    base = root if root is not None else history_dir()
    if not base.exists():
        return
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        path = monthly_history_path(cursor, root=base)
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        play: Play = json.loads(line)
                    except json.JSONDecodeError:
                        # Skip a malformed line rather than crash a
                        # whole wrapped query — the poller may have been
                        # interrupted mid-write.
                        continue
                    played_at = play.get("played_at")
                    if not played_at:
                        continue
                    ts = _parse_iso(played_at)
                    if ts is None:
                        continue
                    if start <= ts < end:
                        yield play
        # Advance one month at a time. The naive +31d / replace(day=1)
        # idiom is good enough since we just need the next month.
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seen_artist_ids_before(start: datetime, root: Path | None = None) -> set[str]:
    """Artist IDs the user heard at any point before ``start``.

    Used to compute the ``new_artists`` field in :func:`build_wrapped`:
    artists that appear inside the window but not in any earlier play.
    """
    seen: set[str] = set()
    base = root if root is not None else history_dir()
    if not base.exists():
        return seen
    for path in sorted(base.glob("history-*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    play: Play = json.loads(line)
                except json.JSONDecodeError:
                    continue
                played_at = play.get("played_at")
                ts = _parse_iso(played_at) if played_at else None
                if ts is None or ts >= start:
                    continue
                for artist_id in _artist_ids_for(play):
                    seen.add(artist_id)
    return seen


def _artist_ids_for(play: Play) -> Iterable[str]:
    track = play.get("track") or {}
    for artist in track.get("artists") or []:
        aid = artist.get("id")
        if aid:
            yield str(aid)


# ----------------------------------------------------------------------
# Building the wrapped JSON
# ----------------------------------------------------------------------


def _window_range(window: Window, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - _WINDOW_DELTA[window]
    return start, end


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_daily_hist(start: datetime, end: datetime) -> dict[str, int]:
    days: dict[str, int] = {}
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        days[cursor.strftime("%Y-%m-%d")] = 0
        cursor += timedelta(days=1)
    return days


def _empty_hour_hist() -> dict[str, int]:
    return {f"{h}": 0 for h in range(24)}


def _build_from_local(
    *,
    window: Window,
    plays: list[Play],
    prior_artist_ids: set[str],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    artist_counts: Counter[str] = Counter()
    artist_meta: dict[str, dict[str, Any]] = {}
    track_counts: Counter[str] = Counter()
    track_meta: dict[str, dict[str, Any]] = {}
    genre_counts: Counter[str] = Counter()
    daily = _empty_daily_hist(start, end)
    hourly = _empty_hour_hist()

    for play in plays:
        track = play.get("track") or {}
        track_id = track.get("id")
        track_uri = track.get("uri")
        ts = _parse_iso(play.get("played_at", ""))
        if ts is None:
            continue
        # Histograms
        day_key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if day_key in daily:
            daily[day_key] += 1
        hourly[str(ts.astimezone(timezone.utc).hour)] += 1
        # Tracks
        if track_id:
            track_counts[track_id] += 1
            if track_id not in track_meta:
                track_meta[track_id] = {
                    "id": track_id,
                    "name": track.get("name"),
                    "uri": track_uri,
                    "external_urls": track.get("external_urls", {}),
                    "artist": _primary_artist_name(track),
                    "album": (track.get("album") or {}).get("name"),
                }
        # Artists
        for artist in track.get("artists") or []:
            aid = artist.get("id")
            if not aid:
                continue
            artist_counts[aid] += 1
            if aid not in artist_meta:
                artist_meta[aid] = {
                    "id": aid,
                    "name": artist.get("name"),
                    "uri": artist.get("uri"),
                    "external_urls": artist.get("external_urls", {}),
                    "genres": artist.get("genres") or [],
                }
            for genre in artist.get("genres") or []:
                genre_counts[genre] += 1

    top_artists = [
        {**artist_meta[aid], "play_count": count} for aid, count in artist_counts.most_common(20)
    ]
    top_tracks = [
        {**track_meta[tid], "play_count": count} for tid, count in track_counts.most_common(50)
    ]
    top_genres = [{"genre": g, "count": n} for g, n in genre_counts.most_common(20)]
    new_artists = [artist_meta[aid] for aid in artist_counts if aid not in prior_artist_ids]
    return {
        "window": window,
        "from": _iso(start),
        "to": _iso(end),
        "source": "local",
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "top_genres": top_genres,
        "total_plays": (
            sum(artist_counts.values()) if False else len(plays)  # plays counted per artist
        ),
        "unique_artists": len(artist_counts),
        "new_artists": new_artists,
        "daily_play_histogram": daily,
        "hour_of_day_histogram": hourly,
    }


def _primary_artist_name(track: dict[str, Any]) -> str | None:
    artists = track.get("artists") or []
    if not artists:
        return None
    name = artists[0].get("name")
    return str(name) if name is not None else None


def _build_from_top_fallback(
    *,
    client: SpotifyClient,
    window: Window,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Populate as much of the wrapped shape as ``/me/top`` allows."""
    time_range = _TIME_RANGE_FOR_WINDOW[window]
    artists_payload = client.get_top("artists", time_range=time_range, limit=20)
    tracks_payload = client.get_top("tracks", time_range=time_range, limit=50)
    artists = artists_payload.get("items") or []
    tracks = tracks_payload.get("items") or []

    top_artists = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "uri": a.get("uri"),
            "external_urls": a.get("external_urls", {}),
            "genres": a.get("genres") or [],
            "play_count": None,  # /me/top doesn't expose play counts
        }
        for a in artists
    ]
    top_tracks = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "uri": t.get("uri"),
            "external_urls": t.get("external_urls", {}),
            "artist": _primary_artist_name(t),
            "album": (t.get("album") or {}).get("name"),
            "play_count": None,
        }
        for t in tracks
    ]
    genre_counts: Counter[str] = Counter()
    for a in artists:
        for g in a.get("genres") or []:
            genre_counts[g] += 1
    top_genres = [{"genre": g, "count": n} for g, n in genre_counts.most_common(20)]
    return {
        "window": window,
        "from": _iso(start),
        "to": _iso(end),
        "source": "top_fallback",
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "top_genres": top_genres,
        "total_plays": 0,  # no play count from /me/top
        "unique_artists": len(top_artists),
        "new_artists": [],
        "daily_play_histogram": {},
        "hour_of_day_histogram": {},
    }


def build_wrapped(
    *,
    window: Window,
    client: SpotifyClient,
    now: datetime | None = None,
    history_root: Path | None = None,
) -> dict[str, Any]:
    """Build the wrapped summary for ``window``.

    Reads from the local poller jsonl when any plays fall within the
    window; otherwise falls back to Spotify's ``/me/top`` with the
    matching ``time_range``. The fallback populates top artists / tracks
    / genres but leaves the histograms empty (Spotify doesn't expose
    per-play timestamps via ``/me/top``).
    """
    start, end = _window_range(window, now=now)
    plays = list(_iter_plays_for_range(start, end, root=history_root))
    if plays:
        prior = _seen_artist_ids_before(start, root=history_root)
        return _build_from_local(
            window=window,
            plays=plays,
            prior_artist_ids=prior,
            start=start,
            end=end,
        )
    return _build_from_top_fallback(client=client, window=window, start=start, end=end)
