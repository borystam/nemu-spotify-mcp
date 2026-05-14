"""Minimal Spotify Web API client with automatic refresh-token handling."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

API_BASE = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Refresh a bit before nominal expiry to absorb clock skew.
_EXPIRY_BUFFER_SECONDS = 30


@dataclass
class _AccessToken:
    value: str
    expires_at: float  # epoch seconds


class SpotifyClient:
    """A tiny synchronous Spotify API client.

    Phase 0 only exposes :meth:`me` and the low-level :meth:`get` and
    :meth:`post` primitives; Phase 1 adds typed wrappers for every
    read-only endpoint we expose as MCP tools.
    """

    def __init__(
        self,
        client_id: str,
        refresh_token: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client_id = client_id
        self._refresh_token = refresh_token
        self._http = http if http is not None else httpx.Client(timeout=timeout)
        self._owns_http = http is None
        self._access: _AccessToken | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> SpotifyClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def refresh_token(self) -> str:
        """The current refresh token (may have rotated since construction)."""
        return self._refresh_token

    def _refresh(self) -> None:
        r = self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        data = r.json()
        self._access = _AccessToken(
            value=data["access_token"],
            expires_at=time.time() + int(data["expires_in"]) - _EXPIRY_BUFFER_SECONDS,
        )
        # Spotify may rotate the refresh token on refresh; if it does, keep the new one.
        new_rt = data.get("refresh_token")
        if new_rt:
            self._refresh_token = new_rt

    def _access_token(self) -> str:
        if self._access is None or self._access.expires_at <= time.time():
            self._refresh()
        assert self._access is not None  # for mypy after refresh
        return self._access.value

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET ``{API_BASE}{path}`` with an authorised request."""
        r = self._http.get(
            f"{API_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def me(self) -> dict[str, Any]:
        """``GET /me`` — the authenticated user's profile."""
        return self.get("/me")
