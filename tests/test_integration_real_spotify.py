"""Integration tests that hit the real Spotify Web API.

Skipped unless ``SPOTIFY_INTEGRATION_TESTS=1`` is set in the environment
AND a valid credentials file exists at the default location. These tests
are intentionally minimal in Phase 0 — Phase 1 expands them to cover
every tool.

To run::

    spotify-wrapped-mcp-auth     # once
    SPOTIFY_INTEGRATION_TESTS=1 pytest -m integration
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SPOTIFY_INTEGRATION_TESTS") != "1",
    reason="set SPOTIFY_INTEGRATION_TESTS=1 to run (will hit api.spotify.com)",
)


@pytest.mark.integration
def test_me_returns_real_profile() -> None:
    from spotify_wrapped_mcp import Credentials, SpotifyClient

    creds = Credentials.load()
    with SpotifyClient(creds.client_id, creds.refresh_token) as c:
        me = c.me()
    assert "id" in me
    assert "display_name" in me
    assert me.get("product") in {"premium", "free", "open"}
