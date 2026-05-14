"""Smoke-test the stored credentials by calling ``GET /me``.

This is what ``spotify-wrapped-mcp test`` does under the hood. Use this
file as a starting point if you want to wrap the smoke test in your own
script (e.g. a health check).

Run::

    python examples/01_smoke_test.py
"""

from __future__ import annotations

import sys

import httpx

from spotify_wrapped_mcp import Credentials, SpotifyClient


def main() -> int:
    try:
        creds = Credentials.load()
    except FileNotFoundError as e:
        print(f"No credentials found: {e}", file=sys.stderr)
        print("Run `spotify-wrapped-mcp-auth` first.", file=sys.stderr)
        return 2

    try:
        with SpotifyClient(creds.client_id, creds.refresh_token) as client:
            profile = client.me()
    except httpx.HTTPStatusError as e:
        print(f"Spotify returned HTTP {e.response.status_code}", file=sys.stderr)
        return 1

    # Print only structural fields, never values that identify the user.
    print("HTTP 200 OK")
    print(f"  product      : {profile.get('product')}")
    print(f"  country      : {profile.get('country')}")
    print(f"  display_name : {'<set>' if profile.get('display_name') else '<unset>'}")
    print(f"  followers    : {profile.get('followers', {}).get('total')}")
    print(f"  scope        : {creds.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
