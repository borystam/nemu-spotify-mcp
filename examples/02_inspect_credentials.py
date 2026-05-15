"""Show where credentials are stored and what they (safely) contain.

Helps when you're not sure whether ``spotify-wrapped-mcp-auth`` has been
run, or where the credentials file ended up on a non-standard system.

Run::

    python examples/02_inspect_credentials.py
"""

from __future__ import annotations

from spotify_wrapped_mcp.config import Credentials, config_dir, credentials_path


def _redact(value: str) -> str:
    """Return ``"first6…last4"`` so we never leak a full secret."""
    if len(value) <= 12:
        return "<short>"
    return f"{value[:6]}…{value[-4:]}"


def main() -> int:
    print(f"config_dir()       : {config_dir()}")
    print(f"credentials_path() : {credentials_path()}")
    if not credentials_path().exists():
        print("(no credentials file present — run `spotify-wrapped-mcp-auth`)")
        return 1

    creds = Credentials.load()
    print(f"client_id          : {creds.client_id}")  # client_id is public
    print(f"refresh_token      : {_redact(creds.refresh_token)}")  # never print full token
    print(f"scope              : {creds.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
