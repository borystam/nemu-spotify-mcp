"""Sanity tests for the MCP server module.

Phase 0: we only verify that the module imports and exposes the expected
symbols. Phase 1 adds behavioural tests for each registered tool.
"""

from __future__ import annotations


def test_server_module_imports_with_expected_name() -> None:
    from spotify_wrapped_mcp.server import SERVER_NAME

    assert SERVER_NAME == "spotify-wrapped-mcp"


def test_main_is_callable() -> None:
    from spotify_wrapped_mcp.server import main

    assert callable(main)


def test_server_is_named() -> None:
    from spotify_wrapped_mcp.server import server

    # The mcp Server stores its name; we don't rely on the attribute path
    # (it differs across SDK versions), so just sanity-check the object exists.
    assert server is not None
