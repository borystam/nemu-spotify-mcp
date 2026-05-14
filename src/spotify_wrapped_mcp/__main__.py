"""Allow `python -m spotify_wrapped_mcp` to run the MCP server."""

from __future__ import annotations

from .cli.main import main

raise SystemExit(main())
