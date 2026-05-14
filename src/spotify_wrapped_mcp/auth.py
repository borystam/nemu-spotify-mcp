"""Spotify OAuth 2.0 PKCE authorization-code flow.

This module is library-only: the CLI wrapper lives in
``spotify_wrapped_mcp.cli.auth``. Splitting them lets us unit-test
:func:`build_authorize_url` and :func:`exchange_code` without spinning up
a web browser.
"""

from __future__ import annotations

import http.server
import secrets
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx

from .pkce import challenge_from_verifier, generate_verifier

AUTHORIZE_URL: Final = "https://accounts.spotify.com/authorize"
TOKEN_URL: Final = "https://accounts.spotify.com/api/token"
DEFAULT_REDIRECT_URI: Final = "http://127.0.0.1:8765/callback"

SCOPES: Final[tuple[str, ...]] = (
    "user-read-recently-played",
    "user-top-read",
    "user-library-read",
    "playlist-read-private",
    "user-read-currently-playing",
    "user-read-playback-state",
)


@dataclass(frozen=True)
class TokenResponse:
    """The fields we care about from Spotify's ``/api/token`` response."""

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    token_type: str


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scopes: tuple[str, ...] = SCOPES,
) -> str:
    """Construct the ``/authorize`` URL the user opens in a browser."""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
        "scope": " ".join(scopes),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client: httpx.Client | None = None,
) -> TokenResponse:
    """POST ``/api/token`` with the auth code to mint access + refresh tokens."""
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    own = client is None
    http = client if client is not None else httpx.Client(timeout=15.0)
    try:
        r = http.post(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            http.close()
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=int(data["expires_in"]),
        scope=data["scope"],
        token_type=data["token_type"],
    )


@dataclass
class _CallbackResult:
    code: str | None = None
    error: str | None = None


def _make_handler(
    state: str,
    result: _CallbackResult,
    done: threading.Event,
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if "error" in qs:
                result.error = qs["error"][0]
            elif qs.get("state", [""])[0] != state:
                result.error = "state_mismatch"
            elif "code" not in qs:
                result.error = "no_code"
            else:
                result.code = qs["code"][0]
            ok = result.code is not None
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = (
                b"<h1>OK</h1><p>You can close this tab and return to your terminal.</p>"
                if ok
                else f"<h1>Auth failed: {result.error}</h1>".encode()
            )
            self.wfile.write(body)
            done.set()

        def log_message(self, format: str, *args: object) -> None:
            # Silence the default access log.
            return

    return _Handler


def run_pkce_flow(
    client_id: str,
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    timeout_seconds: float = 300.0,
    open_browser: bool = True,
    notify: Callable[[str], None] | None = None,
) -> TokenResponse:
    """Run the full PKCE authorization-code flow end-to-end (blocking).

    1. Generate a fresh verifier + S256 challenge + state.
    2. Spin up a one-shot HTTP server on the loopback redirect URI.
    3. Open the authorize URL in a browser (unless ``open_browser=False``).
    4. Block until the callback arrives (or ``timeout_seconds`` elapses).
    5. Exchange the code for tokens and return them.

    ``notify`` is an optional ``print``-like callback used to emit progress
    messages; defaults to silent. The CLI wrapper passes ``print``.
    """
    notify = notify or (lambda _msg: None)

    verifier = generate_verifier()
    challenge = challenge_from_verifier(verifier)
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
    )

    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765

    result = _CallbackResult()
    done = threading.Event()
    handler = _make_handler(state, result, done)
    server = http.server.HTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        notify(f"Open this URL in a browser to authorize:\n\n  {url}\n")
        if open_browser:
            webbrowser.open(url)
        notify(f"Waiting for callback at {redirect_uri} (timeout {int(timeout_seconds)}s)…")
        if not done.wait(timeout=timeout_seconds):
            raise TimeoutError("OAuth callback did not arrive in time.")
    finally:
        server.shutdown()
        server.server_close()

    if result.error or result.code is None:
        raise RuntimeError(f"OAuth failed: {result.error}")

    return exchange_code(
        client_id=client_id,
        code=result.code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
    )
