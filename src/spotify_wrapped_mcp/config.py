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
ROTATED_FILENAME = "rotated_token.json"

# Environment-variable fallback names. Kept in one place so the rest of
# the codebase imports them rather than spelling them inline.
CLIENT_ID_ENV = "SPOTIFY_CLIENT_ID"
REFRESH_TOKEN_ENV = "SPOTIFY_REFRESH_TOKEN"
SCOPE_ENV = "SPOTIFY_SCOPE"
ROTATED_PATH_ENV = "SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE"


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


def rotated_token_path() -> Path:
    """Return the path where rotated refresh tokens are persisted.

    Precedence:
      1. ``$SPOTIFY_WRAPPED_MCP_ROTATED_TOKEN_FILE`` if set (intended
         for deployments where the canonical seed lives in a remote
         secret store and the local filesystem is the only place we
         can write rotations — e.g. hermes-agent reading
         ``op://...`` and writing rotated tokens to
         ``~/.hermes/spotify-rotated.json``).
      2. ``<config_dir>/rotated_token.json``.

    Stored as JSON: ``{"client_id": "...", "refresh_token": "..."}``.
    The client_id pin guards against using a rotated token from a
    previous bootstrap with a different OAuth app.
    """
    override = os.environ.get(ROTATED_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return config_dir() / ROTATED_FILENAME


def write_rotated_token(client_id: str, refresh_token: str, path: Path | None = None) -> Path:
    """Persist a rotated refresh token. Safe to call from arbitrary threads.

    Writes atomically (tmp + rename) and chmods 0600 on POSIX. The
    client_id is stored alongside the token so subsequent
    :meth:`Credentials.load` calls can drop the file if the user has
    re-bootstrapped against a different OAuth app since then.
    """
    p = path or rotated_token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = {"client_id": client_id, "refresh_token": refresh_token}
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return p


def read_rotated_token(client_id: str, path: Path | None = None) -> str | None:
    """Return a rotated refresh token if one is on disk and matches
    ``client_id``. Returns ``None`` otherwise (missing file, mismatched
    client_id, or corrupt JSON — all silent, since the caller has a
    valid seed to fall back to)."""
    p = path or rotated_token_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("client_id") != client_id:
        return None
    rt = data.get("refresh_token")
    return rt if isinstance(rt, str) and rt else None


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

        Order of precedence (each step picks a seed pair, then the
        rotated-token override is applied if present and client_id-matched):

        1. ``SPOTIFY_CLIENT_ID`` + ``SPOTIFY_REFRESH_TOKEN`` env vars
           (with optional ``SPOTIFY_SCOPE``). Used when a secrets-
           injection wrapper provides credentials at process start.
        2. A JSON file at the explicit ``path``, or at
           :func:`credentials_path` if ``path`` is ``None``.

        After picking a seed, this method checks for a rotated token
        file (see :func:`rotated_token_path`) and prefers that token if
        its client_id matches the seed's. This lets the
        ``SpotifyClient`` persist Spotify's per-refresh rotations to a
        local file (via the ``on_token_rotation`` callback) and survive
        process restarts without the canonical seed in 1Password / k8s
        / etc. being touched.

        Raises ``FileNotFoundError`` with a helpful message if neither
        seed source resolves a usable pair.
        """
        client_id: str
        refresh_token: str
        scope: str

        env_id = os.environ.get(CLIENT_ID_ENV)
        env_rt = os.environ.get(REFRESH_TOKEN_ENV)
        if env_id and env_rt:
            client_id = env_id
            refresh_token = env_rt
            scope = os.environ.get(SCOPE_ENV, "")
        else:
            p = path or credentials_path()
            if not p.exists():
                raise FileNotFoundError(
                    f"Credentials not found at {p} and neither {CLIENT_ID_ENV} nor "
                    f"{REFRESH_TOKEN_ENV} is set in the environment. Run "
                    f"`spotify-wrapped-mcp-auth` to create the file, or export the "
                    f"two env vars."
                )
            data = json.loads(p.read_text(encoding="utf-8"))
            client_id = data["client_id"]
            refresh_token = data["refresh_token"]
            scope = data["scope"]

        rotated = read_rotated_token(client_id)
        if rotated:
            refresh_token = rotated
        return cls(client_id=client_id, refresh_token=refresh_token, scope=scope)

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
