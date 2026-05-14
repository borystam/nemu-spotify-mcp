"""Unit tests for spotify_wrapped_mcp.config."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spotify_wrapped_mcp.config import (
    CONFIG_ENV,
    CREDENTIALS_FILENAME,
    Credentials,
    config_dir,
    credentials_path,
)


class TestConfigDir:
    def test_honours_explicit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "custom"))
        assert config_dir() == tmp_path / "custom"

    def test_expands_tilde_in_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CONFIG_ENV, "~/somewhere")
        assert config_dir() == Path.home() / "somewhere"

    def test_uses_xdg_config_home_when_no_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(CONFIG_ENV, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert config_dir() == tmp_path / "xdg" / "spotify-wrapped-mcp"

    def test_falls_back_to_home_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(CONFIG_ENV, raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert config_dir() == tmp_path / ".config" / "spotify-wrapped-mcp"


class TestCredentialsPath:
    def test_resolves_inside_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONFIG_ENV, str(tmp_path))
        assert credentials_path() == tmp_path / CREDENTIALS_FILENAME


class TestCredentialsSaveAndLoad:
    def test_round_trip(self, tmp_path: Path) -> None:
        original = Credentials(client_id="cid", refresh_token="rtok", scope="user-top-read")
        original.save(tmp_path / "creds.json")
        loaded = Credentials.load(tmp_path / "creds.json")
        assert loaded == original

    def test_json_shape_is_stable(self, tmp_path: Path) -> None:
        p = tmp_path / "creds.json"
        Credentials(client_id="cid", refresh_token="rt", scope="sco").save(p)
        data = json.loads(p.read_text())
        assert data == {"client_id": "cid", "refresh_token": "rt", "scope": "sco"}

    def test_save_writes_trailing_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "creds.json"
        Credentials(client_id="a", refresh_token="b", scope="c").save(p)
        assert p.read_text().endswith("\n")

    def test_save_returns_path(self, tmp_path: Path) -> None:
        p = tmp_path / "creds.json"
        result = Credentials(client_id="a", refresh_token="b", scope="c").save(p)
        assert result == p

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "creds.json"
        Credentials(client_id="a", refresh_token="b", scope="c").save(deep)
        assert deep.exists()

    def test_save_uses_atomic_rename(self, tmp_path: Path) -> None:
        p = tmp_path / "creds.json"
        Credentials(client_id="a", refresh_token="b", scope="c").save(p)
        assert not list(tmp_path.glob("*.tmp")), "atomic .tmp should be cleaned up"

    @pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod check")
    def test_file_mode_is_0600(self, tmp_path: Path) -> None:
        p = tmp_path / "creds.json"
        Credentials(client_id="a", refresh_token="b", scope="c").save(p)
        assert (p.stat().st_mode & 0o777) == 0o600

    def test_load_uses_default_path_when_unspecified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONFIG_ENV, str(tmp_path))
        Credentials(client_id="cid", refresh_token="rt", scope="s").save()
        loaded = Credentials.load()
        assert loaded.client_id == "cid"


class TestCredentialsLoadErrors:
    def test_missing_file_raises_filenotfounderror(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Credentials.load(tmp_path / "nope.json")

    def test_missing_file_message_points_to_auth_command(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match=r"spotify-wrapped-mcp-auth"):
            Credentials.load(tmp_path / "nope.json")


class TestCredentialsImmutable:
    def test_dataclass_is_frozen(self) -> None:
        import dataclasses

        c = Credentials(client_id="a", refresh_token="b", scope="c")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.client_id = "different"  # type: ignore[misc]
