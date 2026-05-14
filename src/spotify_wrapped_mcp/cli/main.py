"""``spotify-wrapped-mcp`` — main CLI.

Default behaviour (no subcommand) is to run the MCP stdio server, so MCP
clients can spawn this binary directly. The ``test`` subcommand is a
credential smoke-test (``GET /me``); ``serve`` is an explicit alias for
the default.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from .. import __version__
from ..client import SpotifyClient
from ..config import Credentials, credentials_path
from ..server import main as run_server


def _cmd_test(_args: argparse.Namespace) -> int:
    try:
        creds = Credentials.load()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        with SpotifyClient(creds.client_id, creds.refresh_token) as c:
            profile = c.me()
    except httpx.HTTPStatusError as e:
        print(
            f"error: Spotify returned HTTP {e.response.status_code}\n{e.response.text}",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError as e:
        print(f"error: HTTP request failed: {e}", file=sys.stderr)
        return 1

    print("HTTP 200 OK")
    print(f"  display_name : {profile.get('display_name')}")
    print(f"  id           : {profile.get('id')}")
    print(f"  product      : {profile.get('product')}")
    print(f"  country      : {profile.get('country')}")
    print(f"  scopes       : {creds.scope}")
    print(f"  credentials  : {credentials_path()}")
    return 0


def _cmd_serve(_args: argparse.Namespace) -> int:
    return run_server()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotify-wrapped-mcp",
        description=(
            "Read-only Spotify MCP server. Run with no arguments to start the MCP "
            "stdio server (the default mode used by MCP clients). Use the `test` "
            "subcommand to verify your credentials before wiring up a client."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"spotify-wrapped-mcp {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="command")
    sub.add_parser("serve", help="Run the MCP stdio server (default).")
    sub.add_parser("test", help="Smoke-test stored credentials by calling GET /me.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "test":
        return _cmd_test(args)
    return _cmd_serve(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
