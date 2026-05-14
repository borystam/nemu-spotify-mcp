"""``spotify-wrapped-mcp-auth`` — PKCE OAuth bootstrap CLI."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from .. import __version__
from ..auth import DEFAULT_REDIRECT_URI, run_pkce_flow
from ..config import Credentials, credentials_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotify-wrapped-mcp-auth",
        description=(
            "Run the Spotify PKCE OAuth flow once and store the resulting "
            "credentials locally. After this succeeds, run "
            "`spotify-wrapped-mcp test` to verify."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"spotify-wrapped-mcp-auth {__version__}",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("SPOTIFY_CLIENT_ID"),
        help="Spotify Developer app Client ID. Falls back to $SPOTIFY_CLIENT_ID.",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help=(
            f"OAuth redirect URI (default: {DEFAULT_REDIRECT_URI}). Must match "
            "the value registered in the Spotify Developer Dashboard exactly."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path to write credentials JSON. Defaults to "
            "~/.config/spotify-wrapped-mcp/credentials.json. Ignored if "
            "--output-env is set."
        ),
    )
    parser.add_argument(
        "--output-env",
        action="store_true",
        help="Print shell `export` lines to stdout instead of writing a file.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open the browser; just print the authorize URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for the OAuth callback (default: 300).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.client_id:
        print(
            "error: --client-id (or $SPOTIFY_CLIENT_ID) is required.\n"
            "Get one at https://developer.spotify.com/dashboard — see docs/OAUTH.md.",
            file=sys.stderr,
        )
        return 2

    try:
        tokens = run_pkce_flow(
            args.client_id,
            redirect_uri=args.redirect_uri,
            open_browser=not args.no_browser,
            timeout_seconds=args.timeout,
            notify=lambda m: print(m, file=sys.stderr),
        )
    except (RuntimeError, TimeoutError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    creds = Credentials(
        client_id=args.client_id,
        refresh_token=tokens.refresh_token,
        scope=tokens.scope,
    )

    if args.output_env:
        print(f"export SPOTIFY_CLIENT_ID={shlex.quote(args.client_id)}")
        print(f"export SPOTIFY_REFRESH_TOKEN={shlex.quote(tokens.refresh_token)}")
        print(f"export SPOTIFY_SCOPE={shlex.quote(tokens.scope)}")
        return 0

    path = creds.save(args.output)
    print(f"Credentials written to: {path}", file=sys.stderr)
    print(f"Granted scopes: {tokens.scope}", file=sys.stderr)
    print(
        "Next step: run `spotify-wrapped-mcp test` to verify against GET /me.",
        file=sys.stderr,
    )
    if path == credentials_path():
        print(f"Default location used: {credentials_path()}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
