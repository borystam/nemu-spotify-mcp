# Architecture

A high-level tour of the codebase, the choices behind it, and the rough
shape of the upcoming phases.

## Layout

```
src/spotify_wrapped_mcp/
├── __init__.py        Public re-exports (SpotifyClient, Credentials).
├── __main__.py        Lets `python -m spotify_wrapped_mcp` run the server.
├── pkce.py            RFC 7636 PKCE helpers — verifier + S256 challenge.
├── config.py          Credentials dataclass + load/save with 0600 mode.
├── auth.py            OAuth flow: authorize URL, code exchange, loopback callback server.
├── client.py          SpotifyClient — synchronous httpx client with refresh-token caching.
├── server.py          MCP stdio server entry — no tools yet (Phase 1).
└── cli/
    ├── main.py        `spotify-wrapped-mcp` — default = server, `test` subcommand.
    ├── auth.py        `spotify-wrapped-mcp-auth` — bootstrap.
    └── poller.py      `spotify-history-poller` — Phase 2 stub.
```

## Design choices

### PKCE, not client-secret

The Spotify Web API supports two OAuth flows. We use **PKCE** because:

- This is an open-source server that runs on each user's own machine — it
  is a *public* client. A client secret would have to be shipped in the
  package or asked from each user separately, both of which are worse than
  no secret at all.
- PKCE refresh tokens **never expire** unless the user revokes the app.
  Practical implication: bootstrap once, then the server keeps working
  forever without user interaction.

The flow runs locally with a tiny one-shot HTTP server on
`127.0.0.1:8765`. We bind the loopback IP (not `localhost`) because
Spotify rejects `localhost` for the redirect URI.

### Synchronous httpx

The MCP Python SDK is async, but Spotify's request volume per tool call is
tiny (1–3 requests typically). We use a synchronous `httpx.Client` for
simpler code paths and easier test mocking. The async server wraps
synchronous tool implementations via the MCP SDK's default execution.

### Credential storage

`Credentials.save()` writes via an atomic rename (`tmp → final`) so
partial writes during a crash can't corrupt the credentials file. On
POSIX we `chmod 0600` before the rename. The default location follows the
XDG Base Directory spec.

We deliberately do **not** persist the access token. It expires in 60
minutes and is regenerated from the refresh token on demand by
`SpotifyClient._refresh()`.

### Refresh-token rotation

Spotify sometimes returns a new `refresh_token` on a refresh response.
When that happens, `SpotifyClient` adopts it in memory. We do **not**
automatically persist the rotated token back to disk in Phase 0 —
something to fix in Phase 1 if rotation turns out to be frequent (it is
not, in our testing, but production-mode apps may differ).

## Phase roadmap

### Phase 0 — scaffolding (this commit)

✅ PKCE auth helper, credentials, HTTP client, MCP server skeleton, CI,
docs.

### Phase 1 — read-only suite

Implement the full tool surface as MCP tools (see CHANGELOG for the
complete list — search, lookup, library, listening history). Each tool:

1. Calls a small, typed wrapper on `SpotifyClient` that maps directly to
   a single Spotify endpoint.
2. Returns JSON that preserves every `uri` and `external_urls` field —
   that's what lets a downstream playback MCP (e.g. a Sonos MCP) act on
   the results without a second lookup.
3. Has ≥ 8 unit tests against `httpx.MockTransport` covering happy path
   + 3+ edge cases.
4. Has ≥ 2 integration tests gated by `SPOTIFY_INTEGRATION_TESTS=1`.

### Phase 2 — aggregations + history poller

`get_wrapped(window='month'|'week'|'year')` produces a structured JSON
object with deterministic shape:

```jsonc
{
  "window": "month",
  "from": "2026-04-14T00:00:00Z",
  "to":   "2026-05-14T00:00:00Z",
  "top_artists":   [ /* up to 20, each with {id, name, uri, play_count, genres[]} */ ],
  "top_tracks":    [ /* up to 50, each with {id, name, uri, artist, album, play_count} */ ],
  "top_genres":    [ /* {genre, count} */ ],
  "total_plays":   0,
  "unique_artists":0,
  "new_artists":   [ /* artists first heard inside the window */ ],
  "daily_play_histogram":   { "2026-04-14": 0, ... },
  "hour_of_day_histogram":  { "0": 0, "1": 0, ..., "23": 0 }
}
```

Storage strategy:

- If `spotify-history-poller` has been running on a cron schedule, we
  aggregate from the local jsonl (`~/.local/share/spotify-wrapped-mcp/
  history-YYYY-MM.jsonl`). One line per play, parsed from
  `/me/player/recently-played` (50-track limit per call, so a 30-minute
  poll cadence is the minimum to avoid gaps for heavy listeners).
- If no local history is available, we fall back to Spotify's `/me/top`
  with `time_range` = `short_term` / `medium_term` / `long_term` and
  populate as much of the schema as we can; histograms come back empty
  but `top_artists`/`top_tracks`/`top_genres` are still populated.

Snapshot tests (`syrupy`) lock the JSON shape so refactors don't
silently break downstream consumers.

### Phase 3+ — examples, comparison table, PyPI release

## Composition with playback MCPs

`spotify-wrapped-mcp` is read-only by design. The Sonos / generic-Spotify
playback MCPs accept `uri` parameters of the form `spotify:track:...` —
exactly what every tool here returns. There is no shared state; the MCP
client (Claude Desktop, Claude Code) routes between them.

## What we explicitly do not do

- **No write paths to Spotify.** No play, pause, skip, queue, follow,
  save, create-playlist. The scopes we request reflect this.
- **No telemetry.** No upstream service. The package talks only to
  `accounts.spotify.com` and `api.spotify.com`.
- **No persistence of access tokens.** Only refresh tokens (long-lived)
  and the public client_id.
- **No LLM calls.** `get_wrapped` returns structured JSON; turning it
  into narrative prose is the caller's job.
