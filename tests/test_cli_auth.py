"""Unit tests for the spotify-wrapped-mcp-auth CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spotify_wrapped_mcp import auth as auth_mod
from spotify_wrapped_mcp.cli import auth as cli_auth
from spotify_wrapped_mcp.config import Credentials, credentials_path


def _fake_tokens() -> auth_mod.TokenResponse:
    return auth_mod.TokenResponse(
        access_token="atok",
        refresh_token="rtok",
        expires_in=3600,
        scope=" ".join(auth_mod.SCOPES),
        token_type="Bearer",
    )


class TestVersionAndHelp:
    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_auth.main(["--version"])
        assert excinfo.value.code == 0

    def test_help_text_mentions_client_id_and_redirect(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_auth.main(["--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--client-id" in out
        assert "--redirect-uri" in out
        assert "127.0.0.1:8765" in out


class TestMissingClientId:
    def test_no_argument_or_env_returns_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        rc = cli_auth.main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "--client-id" in err
        assert "developer.spotify.com" in err


class TestHappyPath:
    def test_writes_credentials_file(
        self,
        isolated_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_auth, "run_pkce_flow", lambda *_a, **_kw: _fake_tokens())
        rc = cli_auth.main(["--client-id", "cid", "--no-browser"])
        assert rc == 0
        loaded = Credentials.load(credentials_path())
        assert loaded.client_id == "cid"
        assert loaded.refresh_token == "rtok"
        assert "user-top-read" in loaded.scope

    def test_writes_to_custom_output_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_auth, "run_pkce_flow", lambda *_a, **_kw: _fake_tokens())
        target = tmp_path / "custom.json"
        rc = cli_auth.main(["--client-id", "cid", "--no-browser", "--output", str(target)])
        assert rc == 0
        assert target.exists()

    def test_reads_client_id_from_env(
        self,
        isolated_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env_cid")
        monkeypatch.setattr(cli_auth, "run_pkce_flow", lambda *_a, **_kw: _fake_tokens())
        rc = cli_auth.main(["--no-browser"])
        assert rc == 0
        assert Credentials.load().client_id == "env_cid"


class TestOutputEnv:
    def test_prints_export_lines(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli_auth, "run_pkce_flow", lambda *_a, **_kw: _fake_tokens())
        rc = cli_auth.main(["--client-id", "cid", "--output-env", "--no-browser"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "export SPOTIFY_CLIENT_ID=" in out
        assert "export SPOTIFY_REFRESH_TOKEN=" in out
        assert "export SPOTIFY_SCOPE=" in out

    def test_output_env_does_not_write_file(
        self,
        isolated_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli_auth, "run_pkce_flow", lambda *_a, **_kw: _fake_tokens())
        cli_auth.main(["--client-id", "cid", "--output-env", "--no-browser"])
        assert not credentials_path().exists()


class TestErrors:
    def test_timeout_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def raise_timeout(*_a: Any, **_kw: Any) -> auth_mod.TokenResponse:
            raise TimeoutError("simulated timeout")

        monkeypatch.setattr(cli_auth, "run_pkce_flow", raise_timeout)
        rc = cli_auth.main(["--client-id", "cid"])
        assert rc == 1
        assert "simulated timeout" in capsys.readouterr().err

    def test_runtime_error_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def raise_runtime(*_a: Any, **_kw: Any) -> auth_mod.TokenResponse:
            raise RuntimeError("OAuth failed: state_mismatch")

        monkeypatch.setattr(cli_auth, "run_pkce_flow", raise_runtime)
        rc = cli_auth.main(["--client-id", "cid"])
        assert rc == 1
        assert "state_mismatch" in capsys.readouterr().err
