# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 0 (scaffolding)

- Project skeleton: `pyproject.toml` with hatchling backend, src layout,
  Python ≥ 3.10, MIT license.
- **PKCE helpers** (`spotify_wrapped_mcp.pkce`): RFC 7636 code-verifier and
  S256 code-challenge generation. Pure-stdlib.
- **Credential storage** (`spotify_wrapped_mcp.config`): XDG-aware
  `credentials.json` at `~/.config/spotify-wrapped-mcp/`, mode `0600`,
  overridable via `$SPOTIFY_WRAPPED_MCP_CONFIG_DIR`.
- **OAuth flow** (`spotify_wrapped_mcp.auth`): full PKCE authorization-code
  flow with a local loopback callback server on `127.0.0.1:8765`. No
  client secret. Six read-only scopes: `user-read-recently-played`,
  `user-top-read`, `user-library-read`, `playlist-read-private`,
  `user-read-currently-playing`, `user-read-playback-state`.
- **Spotify client** (`spotify_wrapped_mcp.client`): minimal `SpotifyClient`
  with refresh-token caching, automatic refresh on expiry, and refresh
  rotation if the server returns a new one.
- **CLI entry points**:
  - `spotify-wrapped-mcp` — runs the MCP stdio server (default) or
    `test` subcommand which calls `GET /me` and prints status.
  - `spotify-wrapped-mcp-auth` — runs the PKCE bootstrap and writes the
    credentials file (or `--output-env` prints shell exports).
  - `spotify-history-poller` — entry point reserved for Phase 2; stub
    exits with a "not yet implemented" message.
- **MCP server stub** (`spotify_wrapped_mcp.server`): registers no tools
  yet; Phase 1 adds the seven raw-analytics tools and Phase 2 the
  `get_wrapped` aggregator.
- **Tests** (28 unit + property tests, all mocked, no real network):
  - `tests/test_pkce.py`: 8 tests including 2 Hypothesis property tests
    for determinism and verifier-byte sizing.
  - `tests/test_config.py`: 8 tests covering XDG resolution, round-trip,
    POSIX permissions, missing-file handling.
  - `tests/test_auth.py`: 5 tests covering authorize-URL construction
    (all six scopes, no client_secret, PKCE params present) and code
    exchange against an `httpx.MockTransport`.
  - `tests/test_client.py`: 6 tests covering refresh-on-expiry, refresh
    caching, refresh-token rotation, and HTTP-error propagation.
  - `tests/test_package.py`: 1 sanity test for the package version
    string.
- **CI** (`.github/workflows/ci.yml`): ruff, black `--check`, isort
  `--check-only`, mypy `--strict`, pytest with coverage, sdist + wheel
  build. Matrix: Python 3.10 / 3.11 / 3.12 on `ubuntu-latest`.
- **Pre-commit** (`.pre-commit-config.yaml`): ruff (auto-fix), black,
  isort, mypy `--strict` (on `src/`).
- **GitHub templates**: bug report, feature request, pull request.
- **Docs**:
  - `docs/OAUTH.md` — Spotify Developer Dashboard walkthrough.
  - `docs/ARCHITECTURE.md` — implementation overview and roadmap.
- **Composition note**: README and `docs/ARCHITECTURE.md` describe the
  pattern for combining this read-only server with a separate playback
  MCP (Sonos, generic Spotify-Connect, Home Assistant). Phase 1 tools
  preserve every Spotify `uri` and `external_urls` field so the
  downstream playback server can act on them without a second lookup.

### Not yet (planned)

- **Phase 1 — read-only suite**: implement the full set of read-only
  tools. Target ≥ 85 % coverage, 8+ unit tests per tool, 2+ integration
  tests per tool (gated by `SPOTIFY_INTEGRATION_TESTS=1`).
  - **Search & lookup**: `search`, `get_track`, `get_tracks`, `get_album`,
    `get_albums`, `get_artist`, `get_artists`, `get_artist_top_tracks`,
    `get_artist_albums`, `get_playlist`, `get_user_profile`,
    `get_audio_features`.
  - **Library & listening**: `get_me`, `get_top`, `get_recently_played`,
    `get_now_playing`, `get_playback_state`, `get_devices`,
    `get_playlists`, `get_saved_tracks`, `get_saved_albums`,
    `get_followed_artists`.
- **Phase 2 — aggregations**: `get_wrapped` (month/week/year summary
  with top artists/tracks/genres + daily/hourly histograms) +
  `spotify-history-poller` CLI + local jsonl storage format. Snapshot
  tests for the wrapped output shape.
- **Phase 3+**: examples gallery, comparison table vs other Spotify MCPs,
  PyPI release.
