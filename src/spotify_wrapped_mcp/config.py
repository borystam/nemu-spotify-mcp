"""Credential file location and load/save.

Credentials are stored as JSON at
``$SPOTIFY_WRAPPED_MCP_CONFIG_DIR`` (if set), else
``$XDG_CONFIG_HOME/spotify-wrapped-mcp``, else
``~/.config/spotify-wrapped-mcp``.

The file is created with ``0600`` permissions on POSIX systems.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_ENV = "SPOTIFY_WRAPPED_MCP_CONFIG_DIR"
CREDENTIALS_FILENAME = "credentials.json"


def config_dir() -> Path:
    """Return the directory where the credentials file lives."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "spotify-wrapped-mcp"


def credentials_path() -> Path:
    """Return the full path to ``credentials.json``."""
    return config_dir() / CREDENTIALS_FILENAME


@dataclass(frozen=True)
class Credentials:
    """Persistent Spotify credentials (client_id + refresh_token + scope).

    Access tokens are *not* persisted — they're 1-hour-lived and cached in
    memory by ``SpotifyClient``. Only the long-lived refresh token, the
    public client_id, and the granted scope string are stored.
    """

    client_id: str
    refresh_token: str
    scope: str

    @classmethod
    def load(cls, path: Path | None = None) -> Credentials:
        """Load credentials from ``path`` (default: :func:`credentials_path`).

        Raises ``FileNotFoundError`` with a helpful message if missing.
        """
        p = path or credentials_path()
        if not p.exists():
            raise FileNotFoundError(
                f"Credentials not found at {p}. Run `spotify-wrapped-mcp-auth` first."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            client_id=data["client_id"],
            refresh_token=data["refresh_token"],
            scope=data["scope"],
        )

    def save(self, path: Path | None = None) -> Path:
        """Write credentials atomically; ``chmod 0600`` on POSIX."""
        p = path or credentials_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        return p
