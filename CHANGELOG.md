# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 1 (read-only tool suite)

- **22 MCP tools registered** in
  ``spotify_wrapped_mcp.server`` and dispatched via a name→handler
  registry. Each tool maps to exactly one Spotify endpoint and returns
  its JSON verbatim, preserving every ``uri`` /  ``external_urls`` /
  ``href`` field so a downstream playback MCP (Sonos, generic
  Spotify-Connect) can consume results without a second lookup.
  - **Search & lookup (12):** ``search``, ``get_track``, ``get_tracks``,
    ``get_album``, ``get_albums``, ``get_artist``, ``get_artists``,
    ``get_artist_top_tracks``, ``get_artist_albums``, ``get_playlist``,
    ``get_user_profile``, ``get_audio_features``.
  - **Library & listening (10):** ``get_me``, ``get_top``,
    ``get_recently_played``, ``get_now_playing``,
    ``get_playback_state``, ``get_devices``, ``get_playlists``,
    ``get_saved_tracks``, ``get_saved_albums``, ``get_followed_artists``.
- **Typed wrappers on ``SpotifyClient``** for every endpoint above.
  Bulk-lookup helpers (``get_tracks`` / ``get_albums`` / ``get_artists``
  / ``get_audio_features``) enforce Spotify's per-endpoint ID caps
  client-side so callers see a ``ValueError`` rather than a 400
  round-trip. Cursor-paginated endpoints
  (``get_recently_played``, ``get_followed_artists``) take their cursors
  as keyword args. ``/me/player/currently-playing`` and ``/me/player``
  return ``{}`` cleanly on 204 No Content rather than crashing.
- **``SpotifyDeprecatedForNewAppsError``** typed exception for the
  endpoints Spotify restricted to pre-2024-11-27 apps
  (``/audio-features``, ``/audio-analysis``, ``/recommendations``,
  ``/related-artists``). The MCP layer unwraps it into a structured
  ``{"error": "deprecated_for_new_apps", ...}`` payload so agents can
  explain the situation to users instead of surfacing a bare HTTP error.
- **Composition-with-Sonos design**: the README and tool descriptions
  flag URI hand-off explicitly so an agent can chain
  ``get_artist_top_tracks(artist_id=…)[0]['uri']`` →
  ``sonos_play(content=uri, zone=…)`` with no parser glue. ``get_top``
  + ``get_recently_played`` + ``get_wrapped`` (Phase 2) are the
  primary feeders for a music-routing skill on the agent side.
- **Tests** (147 new unit tests, all mocked, no real network):
  - ``tests/test_client_search_lookup.py``: 38 tests including bulk-cap
    enforcement, comma-encoded ID lists, parameter forwarding, empty
    results, 4xx and 429 propagation, and the deprecated-for-new-apps
    gate firing on 403 and 404 but **not** on non-deprecated endpoints.
  - ``tests/test_client_library.py``: 25 tests covering each ``/me/*``
    endpoint's path, default and explicit pagination, cursor ``after`` /
    ``before`` propagation, 204-No-Content handling on now-playing and
    playback-state, and devices/saved/followed shapes.
  - ``tests/test_server_tools.py``: 22 tests covering the
    ``list_tools()`` registration (22 tools registered, every descriptor
    well-formed, required-args declared), and ``call_tool()`` dispatch
    (each tool routes to the matching ``SpotifyClient`` method with
    correct keyword shape; response is a single JSON-encoded
    ``TextContent``; unknown tool raises; deprecated-for-new-apps
    payload is unwrapped to a structured error).
- ``ruff check``, ``black --check``, ``isort --check-only``, and
  ``mypy --strict`` all pass on the new code.

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

- **Phase 2 — aggregations**: `get_wrapped` (month/week/year summary
  with top artists/tracks/genres + daily/hourly histograms) +
  `spotify-history-poller` CLI + local jsonl storage format. Snapshot
  tests for the wrapped output shape.
- **Phase 3+**: examples gallery, comparison table vs other Spotify MCPs,
  PyPI release.
