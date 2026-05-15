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


class TestLoadFromEnv:
    """Env-var fallback for hermes / op-run / k8s secrets deployments."""

    def test_env_takes_precedence_over_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # File with one set of creds...
        path = tmp_path / "credentials.json"
        path.write_text(
            json.dumps(
                {
                    "client_id": "from-file",
                    "refresh_token": "rt-file",
                    "scope": "scope-file",
                }
            )
        )
        # ...env with a different set
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "from-env")
        monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "rt-env")
        monkeypatch.setenv("SPOTIFY_SCOPE", "scope-env")
        creds = Credentials.load(path)
        assert creds.client_id == "from-env"
        assert creds.refresh_token == "rt-env"
        assert creds.scope == "scope-env"

    def test_env_without_file_works(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "only-env")
        monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "rt-only-env")
        monkeypatch.delenv("SPOTIFY_SCOPE", raising=False)
        # Point credentials_path at a non-existent file
        monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "nope"))
        creds = Credentials.load()
        assert creds.client_id == "only-env"
        assert creds.scope == ""

    def test_partial_env_falls_through_to_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Setting only ONE of the two env vars must not silently mask
        the file — the user almost certainly meant to set both, and the
        safer failure mode is to use the file (or surface the missing
        var clearly)."""
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "only-id")
        monkeypatch.delenv("SPOTIFY_REFRESH_TOKEN", raising=False)
        path = tmp_path / "credentials.json"
        path.write_text(
            json.dumps(
                {
                    "client_id": "from-file",
                    "refresh_token": "rt-file",
                    "scope": "scope-file",
                }
            )
        )
        creds = Credentials.load(path)
        assert creds.client_id == "from-file"

    def test_no_env_no_file_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_REFRESH_TOKEN", raising=False)
        monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "nope"))
        with pytest.raises(FileNotFoundError, match="SPOTIFY_CLIENT_ID"):
            Credentials.load()


class TestRotatedTokenFile:
    """Persistence of rotated refresh tokens."""

    def test_write_and_read_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import (
            read_rotated_token,
            rotated_token_path,
            write_rotated_token,
        )

        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(tmp_path / "rot.json"))
        p = write_rotated_token("cid-A", "rt-new")
        assert p == rotated_token_path()
        assert read_rotated_token("cid-A") == "rt-new"

    def test_read_returns_none_when_client_id_mismatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import read_rotated_token, write_rotated_token

        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(tmp_path / "rot.json"))
        write_rotated_token("cid-A", "rt-new")
        # Different OAuth app — must not return the rotated token
        assert read_rotated_token("cid-B") is None

    def test_read_returns_none_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import read_rotated_token

        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(tmp_path / "missing.json"))
        assert read_rotated_token("cid") is None

    def test_read_returns_none_on_corrupt_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import read_rotated_token

        bad = tmp_path / "rot.json"
        bad.write_text("not json {")
        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(bad))
        assert read_rotated_token("cid") is None

    def test_write_is_chmod_600_on_posix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import write_rotated_token

        path = tmp_path / "rot.json"
        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(path))
        write_rotated_token("cid", "rt")
        if os.name == "posix":
            assert (path.stat().st_mode & 0o777) == 0o600

    def test_load_prefers_rotated_token_over_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import write_rotated_token

        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
        monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "rt-from-env-stale")
        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(tmp_path / "rot.json"))
        write_rotated_token("cid", "rt-fresh-rotated")
        creds = Credentials.load()
        assert creds.refresh_token == "rt-fresh-rotated"

    def test_load_falls_back_to_env_when_client_id_mismatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from spotify_wrapped_mcp.config import write_rotated_token

        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid-NEW")
        monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "rt-from-env")
        monkeypatch.setenv("SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE", str(tmp_path / "rot.json"))
        write_rotated_token("cid-OLD", "rt-old-rotated")
        creds = Credentials.load()
        # User re-bootstrapped with a different app; rotated token must
        # not be used.
        assert creds.client_id == "cid-NEW"
        assert creds.refresh_token == "rt-from-env"
