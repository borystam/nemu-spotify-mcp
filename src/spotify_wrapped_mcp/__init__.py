"""spotify-wrapped-mcp — read-only Spotify MCP server.

Public API surface:
    spotify_wrapped_mcp.SpotifyClient   — HTTP client with refresh-token handling
    spotify_wrapped_mcp.Credentials     — credential file load/save
    spotify_wrapped_mcp.__version__     — package version
"""

from __future__ import annotations

from .client import SpotifyClient
from .config import Credentials

__version__ = "0.1.0"
__all__ = ["Credentials", "SpotifyClient", "__version__"]
