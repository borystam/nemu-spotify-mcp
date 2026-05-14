"""Unit tests for the spotify-wrapped-mcp CLI (cli/main.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spotify_wrapped_mcp.cli import main as cli_main
from spotify_wrapped_mcp.config import Credentials


class TestVersionAndHelp:
    def test_version_flag_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_main.main(["--version"])
        assert excinfo.value.code == 0
        assert "spotify-wrapped-mcp" in capsys.readouterr().out

    def test_help_text_lists_test_and_serve(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_main.main(["--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "test" in out
        assert "serve" in out


class TestTestSubcommand:
    def test_missing_credentials_returns_2(
        self,
        isolated_config_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert isolated_config_dir.exists()
        rc = cli_main.main(["test"])
        assert rc == 2
        assert "spotify-wrapped-mcp-auth" in capsys.readouterr().err

    def test_happy_path_prints_profile(
        self,
        isolated_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        Credentials(client_id="cid", refresh_token="rt", scope="user-top-read").save()

        class FakeClient:
            def __init__(self, *_a: Any, **_kw: Any) -> None:
                pass

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *_a: Any) -> None:
                return None

            def me(self) -> dict[str, Any]:
                return {
                    "display_name": "alice_example",
                    "id": "alice_example",
                    "product": "premium",
                    "country": "PL",
                }

        monkeypatch.setattr(cli_main, "SpotifyClient", FakeClient)
        rc = cli_main.main(["test"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "HTTP 200 OK" in out
        assert "alice_example" in out
        assert "premium" in out

    def test_http_error_returns_1(
        self,
        isolated_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        Credentials(client_id="cid", refresh_token="rt", scope="x").save()
        import httpx

        class FakeResponse:
            status_code = 401
            text = '{"error": "no"}'

        class FakeClient:
            def __init__(self, *_a: Any, **_kw: Any) -> None:
                pass

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *_a: Any) -> None:
                return None

            def me(self) -> dict[str, Any]:
                raise httpx.HTTPStatusError(
                    "401", request=httpx.Request("GET", "x"), response=httpx.Response(401)
                )

        monkeypatch.setattr(cli_main, "SpotifyClient", FakeClient)
        rc = cli_main.main(["test"])
        assert rc == 1
        assert "HTTP" in capsys.readouterr().err


class TestServeSubcommand:
    def test_serve_calls_run_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"n": 0}

        def fake_run_server() -> int:
            called["n"] += 1
            return 0

        monkeypatch.setattr(cli_main, "run_server", fake_run_server)
        rc = cli_main.main(["serve"])
        assert rc == 0
        assert called["n"] == 1

    def test_default_no_subcommand_runs_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"n": 0}

        def fake_run_server() -> int:
            called["n"] += 1
            return 0

        monkeypatch.setattr(cli_main, "run_server", fake_run_server)
        rc = cli_main.main([])
        assert rc == 0
        assert called["n"] == 1


class TestArgvParsing:
    def test_unknown_subcommand_rejected(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_main.main(["bogus"])
        assert excinfo.value.code == 2
