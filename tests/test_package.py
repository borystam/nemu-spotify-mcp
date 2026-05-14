"""Sanity tests for the package itself."""

from __future__ import annotations


def test_version_is_a_string() -> None:
    from spotify_wrapped_mcp import __version__

    assert isinstance(__version__, str)
    assert __version__ == "0.1.0"


def test_public_api_exports() -> None:
    import spotify_wrapped_mcp

    assert hasattr(spotify_wrapped_mcp, "SpotifyClient")
    assert hasattr(spotify_wrapped_mcp, "Credentials")
    assert hasattr(spotify_wrapped_mcp, "__version__")
