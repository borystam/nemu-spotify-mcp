"""Credential file location and load/save.

Credentials are loaded from one of three sources, in order:

1. Environment variables ``SPOTIFY_CLIENT_ID`` and
   ``SPOTIFY_REFRESH_TOKEN`` (and optionally ``SPOTIFY_SCOPE``).
   Useful when the server runs under a secrets-injection wrapper —
   ``op run`` for 1Password, systemd ``EnvironmentFile=``, Kubernetes
   secrets, etc. — without needing to materialise a JSON file on disk.
2. A JSON file at the explicit path passed to :meth:`Credentials.load`.
3. The default JSON path: ``$SPOTIFY_WRAPPED_MCP_CONFIG_DIR`` if set,
   else ``$XDG_CONFIG_HOME/spotify-wrapped-mcp``, else
   ``~/.config/spotify-wrapped-mcp``. The file is created with
   ``0600`` on POSIX.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_ENV = "SPOTIFY_WRAPPED_MCP_CONFIG_DIR"
CREDENTIALS_FILENAME = "credentials.json"

# Environment-variable fallback names. Kept in one place so the rest of
# the codebase imports them rather than spelling them inline.
CLIENT_ID_ENV = "SPOTIFY_CLIENT_ID"
REFRESH_TOKEN_ENV = "SPOTIFY_REFRESH_TOKEN"
SCOPE_ENV = "SPOTIFY_SCOPE"


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
        """Load credentials.

        Order of precedence:

        1. ``SPOTIFY_CLIENT_ID`` + ``SPOTIFY_REFRESH_TOKEN`` env vars
           (with optional ``SPOTIFY_SCOPE``). Used when a secrets-
           injection wrapper provides credentials at process start.
        2. A JSON file at the explicit ``path``, or at
           :func:`credentials_path` if ``path`` is ``None``.

        Raises ``FileNotFoundError`` with a helpful message if neither
        source resolves a usable pair.
        """
        env_id = os.environ.get(CLIENT_ID_ENV)
        env_rt = os.environ.get(REFRESH_TOKEN_ENV)
        if env_id and env_rt:
            return cls(
                client_id=env_id,
                refresh_token=env_rt,
                scope=os.environ.get(SCOPE_ENV, ""),
            )
        p = path or credentials_path()
        if not p.exists():
            raise FileNotFoundError(
                f"Credentials not found at {p} and neither {CLIENT_ID_ENV} nor "
                f"{REFRESH_TOKEN_ENV} is set in the environment. Run "
                f"`spotify-wrapped-mcp-auth` to create the file, or export the "
                f"two env vars."
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
