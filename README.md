# spotify-wrapped-mcp

[![CI](https://github.com/borystam/spotify-wrapped-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/borystam/spotify-wrapped-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A **read-only Spotify MCP server** — search, lookup, library, listening
history, and monthly/weekly wrapped aggregations. Works with any MCP client
(Claude Desktop, Claude Code, generic stdio clients).

## Why this exists

The existing Spotify MCP servers
([marcelmarais/spotify-mcp](https://github.com/marcelmarais/spotify-mcp),
[varunneal/spotify-mcp](https://github.com/varunneal/spotify-mcp), and
others) are **playback-focused**: play, pause, skip, queue. There is a gap
for the read-only side of the Spotify Web API — searching, looking up
tracks/artists/albums, browsing your library, your recent listening, and
computed wraps. This server fills that gap.

Playback is intentionally out of scope (zero write paths). If you want
playback control, compose this server with one of the playback-focused
MCPs above, or a hardware integration like a Sonos MCP — see
[**Composition with playback MCPs**](#composition-with-playback-mcps).

## Status

**Phase 1 — read-only tool suite shipped.** 22 MCP tools wired through
typed wrappers on `SpotifyClient` (one Spotify endpoint each), full
unit-test coverage against `httpx.MockTransport`, integration tests
gated by `SPOTIFY_INTEGRATION_TESTS=1`. `get_wrapped` + the history
poller land in Phase 2. See [`CHANGELOG.md`](CHANGELOG.md) for the
current state and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for
the roadmap.

## Planned tools

### Search & lookup
| Tool                     | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `search`                 | Universal search: tracks / artists / albums / playlists.   |
| `get_track`              | Single track details (incl. ISRC, popularity).             |
| `get_tracks`             | Bulk track lookup (≤ 50 IDs).                              |
| `get_album`              | Album metadata + tracklist.                                |
| `get_albums`             | Bulk album lookup (≤ 20 IDs).                              |
| `get_artist`             | Artist metadata (genres, popularity, followers).           |
| `get_artists`            | Bulk artist lookup (≤ 50 IDs).                             |
| `get_artist_top_tracks`  | Top tracks for an artist in a given market.                |
| `get_artist_albums`      | Artist's discography (with `include_groups` filter).       |
| `get_playlist`           | Playlist metadata + tracks.                                |
| `get_user_profile`       | Any user's public profile.                                 |
| `get_audio_features`     | Bulk audio-feature lookup (≤ 100 IDs). *[1]*               |

### Your library & listening
| Tool                     | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `get_me`                 | The authenticated user's profile.                          |
| `get_top`                | Your top artists or tracks (short/medium/long-term).       |
| `get_recently_played`    | Your last N plays with timestamps.                         |
| `get_now_playing`        | What's currently playing + device.                         |
| `get_playback_state`     | Full playback state (device, shuffle, repeat).             |
| `get_devices`            | Devices currently available to this account.               |
| `get_playlists`          | Your playlists.                                            |
| `get_saved_tracks`       | Tracks you've saved/liked.                                 |
| `get_saved_albums`       | Albums you've saved.                                       |
| `get_followed_artists`   | Artists you follow.                                        |

### Aggregations
| Tool                     | Description                                                |
| ------------------------ | ---------------------------------------------------------- |
| `get_wrapped`            | Structured month/week/year summary: top artists/tracks/genres + histograms. Falls back to `/me/top` if no local history is available; aggregates from the poller's local jsonl when it is. |

*[1] `get_audio_features` and a handful of other endpoints were
restricted-for-new-apps by Spotify in November 2024; these tools attempt
the call and return a clear error if the endpoint is unavailable to your
app, rather than failing silently. Older apps continue to work.*

## Install

> Requires Python ≥ 3.10. A Spotify account with **Premium** is needed for
> some endpoints (`/me/player/currently-playing` etc.).

```bash
# Recommended: uvx — auto-installs into an isolated env on first run
uvx spotify-wrapped-mcp --help

# Or pip
pip install spotify-wrapped-mcp
```

## Quick start

1. **Create a Spotify Developer app.** See
   [`docs/OAUTH.md`](docs/OAUTH.md) for the five-minute walkthrough. Copy
   the Client ID. Redirect URI must be exactly
   `http://127.0.0.1:8765/callback`.
2. **Authorize.** Run the bootstrap CLI:
   ```bash
   SPOTIFY_CLIENT_ID=<your-client-id> spotify-wrapped-mcp-auth
   ```
   This runs the PKCE flow (no client secret), opens your browser, captures
   the callback locally, and writes a credentials file to
   `~/.config/spotify-wrapped-mcp/credentials.json` (mode `0600`).
3. **Smoke-test.**
   ```bash
   spotify-wrapped-mcp test
   ```
   Should print `HTTP 200 OK` and your profile.
4. **Wire it into your MCP client.** Example for Claude Desktop
   (`~/Library/Application Support/Claude/claude_desktop_config.json`,
   `%APPDATA%\Claude\claude_desktop_config.json` on Windows, or
   `~/.config/Claude/claude_desktop_config.json` on Linux):
   ```json
   {
     "mcpServers": {
       "spotify-wrapped": {
         "command": "uvx",
         "args": ["spotify-wrapped-mcp"]
       }
     }
   }
   ```
   For Claude Code, add via `claude mcp add` or the equivalent settings file.

## Composition with playback MCPs

`spotify-wrapped-mcp` deliberately exposes no write paths — it cannot
play, pause, or queue anything. The intended pattern is to **compose**
it with a separate playback MCP (a Sonos MCP, a generic Spotify-Connect
MCP, Home Assistant, etc.) by piping URIs from this server's tool
results into the playback server's `play` tool.

Every Spotify object (track, album, artist, playlist) carries both a
Spotify **URI** (e.g. `spotify:track:6rqhFgbbKwnb9MLmUQDhG6`) and an
**external URL** (`https://open.spotify.com/track/…`) in the response.
All of this server's tools preserve those fields so a downstream
playback MCP — or an agent stitching tools together — can act on them
without a second lookup.

Example agent flows:

- *"Play the top track from my most-listened artist this week on Sonos"*:
  → `get_top(type=artists, time_range=short_term)` →
  → `get_artist_top_tracks(artist_id=…)` →
  → `sonos.play(uri=spotify:track:…)`.
- *"Queue the album of the song I'm playing"*:
  → `get_now_playing()` →
  → `get_album(album_id=…)` →
  → `sonos.queue(uris=[…])`.

If you're deploying on the same MCP client (Claude Desktop, Claude
Code), just register both servers in your client config. The client
will route tool calls between them — this server has no awareness of
the playback server and vice versa.

## Privacy

- **No data leaves your machine.** All Spotify API calls go directly from
  this process to `api.spotify.com`. There is no telemetry, no analytics, no
  upstream service.
- **Read-only.** No write scopes are requested. The server cannot start,
  pause, skip, or modify your playlists.
- **Scopes requested** (and why):
  - `user-read-recently-played` — for `get_recently_played` + monthly wraps.
  - `user-top-read` — for `get_top` + wrapped aggregation fallback.
  - `user-library-read` — for saved-tracks counts in wraps.
  - `playlist-read-private` — for `get_playlists` (private playlists).
  - `user-read-currently-playing` + `user-read-playback-state` — for
    `get_now_playing`.
- Credentials live locally at `~/.config/spotify-wrapped-mcp/credentials.json`
  with mode `0600`. PKCE means there is no client secret to leak; refresh
  tokens never expire unless you revoke the app at
  <https://www.spotify.com/account/apps/>.

## Troubleshooting

See [`docs/OAUTH.md`](docs/OAUTH.md). The most common gotchas:

- **`INVALID_CLIENT: Invalid redirect URI`** — the Redirect URI in your
  Spotify Developer Dashboard must match `http://127.0.0.1:8765/callback`
  *exactly* (loopback IP, not `localhost`).
- **`User not registered in the Developer Dashboard`** — your app is in
  Development Mode (the default; 5-user cap) and your Spotify account
  isn't on the User Management list. Add yourself in the dashboard.
- **`product: 'free'`** — some endpoints require Premium. Tools that don't
  will still work.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). TL;DR: `pip install -e ".[dev]"`,
`pre-commit install`, `pytest`.

## License

[MIT](LICENSE).
