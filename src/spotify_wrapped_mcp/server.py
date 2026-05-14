"""MCP stdio server entry point.

Phase 0 registers no tools — Phase 1 adds the read-only suite (search,
lookup, library, listening history) and Phase 2 adds ``get_wrapped``.
The empty ``list_tools`` handler still lets clients connect, list zero
tools, and exit cleanly, which keeps CI's smoke checks green.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__

if TYPE_CHECKING:
    from mcp.types import Tool

SERVER_NAME = "spotify-wrapped-mcp"

server: Server = Server(SERVER_NAME)


@server.list_tools()  # type: ignore[no-untyped-call]
async def list_tools() -> list[Tool]:
    """Return the registered MCP tools. Empty until Phase 1."""
    return []


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> int:
    """Block on the stdio server until the client disconnects. Returns 0."""
    asyncio.run(_serve())
    return 0


__all__ = ["SERVER_NAME", "__version__", "list_tools", "main", "server"]
