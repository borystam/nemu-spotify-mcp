# History poller — cron setup

`spotify-history-poller` snapshots your last ≤ 50 Spotify plays into a
monthly jsonl file. Spotify only exposes a rolling 50-track buffer, so
**you must poll on a schedule** if you want analytics over a longer
window than the most-recent 50 plays.

## Recommended cadence

**Every 30 minutes.** That is the slowest cadence that won't lose plays
for a heavy listener — at one play every ~3 minutes (typical for
back-to-back playlist listening), 50 plays cover ~150 minutes ≈ 2½
hours of music, so the worst-case poll-interval-without-loss is ~2½
hours. The 30-minute setting leaves comfortable headroom even during a
long evening of continuous play.

Light listeners (a handful of plays per day) can poll hourly with no
data loss. There is no upside to polling more often than every 5
minutes — Spotify's rate limits and the redundancy cost outweigh the
freshness gain.

## crontab entry

The poller exits non-zero on transport errors so cron's default mail
behaviour surfaces problems. Pipe to a log if you'd rather inspect by
hand:

```cron
# m  h  dom mon dow  command
  */30 * *   *   *    /usr/local/bin/spotify-history-poller --quiet >> ~/.local/state/spotify-history-poller.log 2>&1
```

If `spotify-history-poller` isn't on `PATH` (e.g. you installed with
`uvx`), use the wrapper:

```cron
*/30 * * * * uvx --from spotify-wrapped-mcp spotify-history-poller --quiet
```

## systemd timer alternative

For systems where cron isn't already running (most modern desktops,
servers behind systemd), prefer a user-level timer:

`~/.config/systemd/user/spotify-history-poller.service`:

```ini
[Unit]
Description=Append Spotify recently-played to local jsonl

[Service]
Type=oneshot
ExecStart=%h/.local/bin/spotify-history-poller --quiet
```

`~/.config/systemd/user/spotify-history-poller.timer`:

```ini
[Unit]
Description=Run spotify-history-poller every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now spotify-history-poller.timer
systemctl --user list-timers --all | grep spotify
```

## Verifying

After the first successful run:

```bash
ls -la "${SPOTIFY_WRAPPED_MCP_HISTORY_DIR:-$HOME/.local/share/spotify-wrapped-mcp}/"
# history-YYYY-MM.jsonl
wc -l "${SPOTIFY_WRAPPED_MCP_HISTORY_DIR:-$HOME/.local/share/spotify-wrapped-mcp}/history-$(date +%Y-%m).jsonl"
```

`get_wrapped(window='month')` will start using the jsonl once it has
any plays in the requested window; before that it transparently falls
back to `/me/top` (top_artists / top_tracks / top_genres present,
histograms empty).

## Storage estimate

Each play is roughly 800-1200 bytes of JSON. At ~50 plays a day for a
heavy listener: ~50 KB/day → ~1.5 MB/month → ~18 MB/year. The history
files are append-only and never rewritten, so the disk impact is
predictable.

## Rotating

There is no automatic rotation. The files are organised by month, so
you can prune anything older than the longest window you care about
(usually `year`) with a simple `find`:

```bash
find "${SPOTIFY_WRAPPED_MCP_HISTORY_DIR:-$HOME/.local/share/spotify-wrapped-mcp}/" \
  -name "history-*.jsonl" -mtime +400 -print
```
