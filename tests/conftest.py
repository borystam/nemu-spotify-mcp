"""Shared pytest fixtures and configuration.

All Phase 0 tests run fully offline; nothing in this file is allowed to
make a real network call. Integration tests (gated by
``SPOTIFY_INTEGRATION_TESTS=1``) live in ``tests/test_integration_*.py``
and bring their own fixtures.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def fake_client_id() -> str:
    return "fakeclientid0000000000000000000a"


@pytest.fixture
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the package at a throw-away config dir for the test."""
    monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_CONFIG_DIR", str(tmp_path))
    return tmp_path


def free_port() -> int:
    """Return a TCP port currently free on 127.0.0.1.

    There is an inherent race between picking and binding, but for tests
    that spin up a one-shot HTTP server the window is tiny.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
