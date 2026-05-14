"""``spotify-history-poller`` — append recently-played tracks to local jsonl.

Spotify exposes only the user's last 50 plays via
``/me/player/recently-played``. For analytics over longer windows we
poll on a cron schedule and append each new play to a monthly
``history-YYYY-MM.jsonl`` file. Recommended cadence: every 30 minutes
(heavy listeners can clear the 50-track buffer in under an hour
otherwise).

Storage path (in precedence order):
  1. ``$SPOTIFY_WRAPPED_MCP_HISTORY_DIR`` if set
  2. ``$XDG_DATA_HOME/spotify-wrapped-mcp``
  3. ``~/.local/share/spotify-wrapped-mcp``

Each line is a JSON object: ``{"track": {...}, "played_at": "..."}``
verbatim from Spotify, so the wrapped aggregator has every field it
needs without re-fetching. Deduplication compares ``played_at``
(unique per play with sub-second precision) against the last ~200
lines already on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..client import SpotifyClient
from ..config import Credentials
from ..wrapped import history_dir, monthly_history_path

# How many recent lines to scan for duplicate detection. 200 covers
# four polls' worth of overlap with comfortable headroom; reading 200
# lines from a jsonl file is cheap even for years of accumulated data.
_DEDUP_TAIL_LINES = 200


def _read_recent_played_at(path: Path, tail_lines: int = _DEDUP_TAIL_LINES) -> set[str]:
    """Return the set of ``played_at`` values from the last N lines."""
    if not path.exists():
        return set()
    seen: set[str] = set()
    # Read the tail without loading the whole file (we don't know how
    # big it'll get over years).
    with path.open("rb") as fh:
        try:
            fh.seek(0, 2)  # end
            size = fh.tell()
            chunk = min(size, 65536)
            fh.seek(max(0, size - chunk))
            data = fh.read().decode("utf-8", errors="replace")
        except OSError:
            data = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    for line in lines[-tail_lines:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        played = obj.get("played_at")
        if played:
            seen.add(played)
    return seen


def _new_plays_for(
    items: Iterable[dict[str, Any]],
    *,
    already_seen: set[str],
) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for item in items:
        played_at = item.get("played_at")
        if not played_at or played_at in already_seen:
            continue
        track = item.get("track")
        if not isinstance(track, dict):
            continue
        fresh.append({"track": track, "played_at": played_at})
        already_seen.add(played_at)
    return fresh


def _append_plays(path: Path, plays: list[dict[str, Any]]) -> None:
    """Append ``plays`` as JSON lines to ``path``. Creates parent dirs.

    Lines may straddle monthly boundaries within a single batch; the
    caller is responsible for grouping plays by month and calling this
    helper once per month-file.
    """
    if not plays:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for play in plays:
            fh.write(json.dumps(play, ensure_ascii=False))
            fh.write("\n")


def _group_by_month(plays: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for play in plays:
        played_at = play.get("played_at")
        if not played_at:
            continue
        try:
            ts = datetime.fromisoformat(played_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        key = ts.strftime("%Y-%m")
        out.setdefault(key, []).append(play)
    return out


def _run_once(client: SpotifyClient, root: Path) -> int:
    payload = client.get_recently_played(limit=50)
    items = payload.get("items") or []
    if not items:
        return 0
    # Sort by played_at so duplicate detection is order-insensitive.
    items_sorted = sorted(items, key=lambda i: i.get("played_at") or "")

    by_month = _group_by_month(
        [{"track": i.get("track"), "played_at": i.get("played_at")} for i in items_sorted]
    )
    appended = 0
    for month_key, month_plays in sorted(by_month.items()):
        ts = datetime.strptime(month_key, "%Y-%m").replace(day=1)
        path = monthly_history_path(ts, root=root)
        seen = _read_recent_played_at(path)
        fresh = _new_plays_for(month_plays, already_seen=seen)
        _append_plays(path, fresh)
        appended += len(fresh)
    return appended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spotify-history-poller",
        description=(
            "Append the most recent <=50 plays to a monthly "
            "history-YYYY-MM.jsonl file. Designed for cron use (every 30 "
            "minutes is sane for heavy listeners)."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Override the history directory. Defaults to "
            "$SPOTIFY_WRAPPED_MCP_HISTORY_DIR / "
            "$XDG_DATA_HOME/spotify-wrapped-mcp / "
            "~/.local/share/spotify-wrapped-mcp."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-run summary line on stdout.",
    )
    args = parser.parse_args(argv)

    try:
        creds = Credentials.load()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    root = args.root.expanduser() if args.root else history_dir()
    try:
        with SpotifyClient(creds.client_id, creds.refresh_token) as client:
            appended = _run_once(client, root)
    except httpx.HTTPStatusError as exc:
        print(
            f"error: Spotify returned HTTP {exc.response.status_code}\n" f"{exc.response.text}",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError as exc:
        print(f"error: HTTP request failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"appended {appended} play(s) to {root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
