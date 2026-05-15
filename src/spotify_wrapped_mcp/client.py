"""Minimal Spotify Web API client with automatic refresh-token handling."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

import httpx

API_BASE = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Refresh a bit before nominal expiry to absorb clock skew.
_EXPIRY_BUFFER_SECONDS = 30

# Spotify bulk-lookup caps. Kept as constants so callers can bin-pack
# their own ID lists rather than waiting on a 400 round-trip.
MAX_IDS_PER_TRACKS_LOOKUP = 50
MAX_IDS_PER_ALBUMS_LOOKUP = 20
MAX_IDS_PER_ARTISTS_LOOKUP = 50
MAX_IDS_PER_AUDIO_FEATURES_LOOKUP = 100

SearchType = Literal["track", "artist", "album", "playlist", "show", "episode", "audiobook"]
TopType = Literal["artists", "tracks"]
TimeRange = Literal["short_term", "medium_term", "long_term"]
IncludeGroups = Literal["album", "single", "appears_on", "compilation"]


@dataclass
class _AccessToken:
    value: str
    expires_at: float  # epoch seconds


class SpotifyDeprecatedForNewAppsError(RuntimeError):
    """Endpoint Spotify restricted to old apps on 2024-11-27.

    Affects ``/audio-features``, ``/audio-analysis``, ``/recommendations``,
    and ``/artists/{id}/related-artists``. Apps created on or after that
    date receive 403 / 404 there permanently. We surface this as a typed
    error so callers (and agents reading the message) can explain the
    situation rather than show a bare ``HTTPStatusError``.
    """


_DEPRECATED_FOR_NEW_APPS_PATHS = (
    "/audio-features",
    "/audio-analysis",
    "/recommendations",
    "/related-artists",
)


def _join_ids(ids: Iterable[str], *, limit: int) -> str:
    """Comma-join Spotify IDs, asserting the endpoint cap up front."""
    materialised = list(ids)
    if not materialised:
        raise ValueError("at least one ID is required")
    if len(materialised) > limit:
        raise ValueError(
            f"too many IDs for one call: got {len(materialised)}, " f"endpoint limit is {limit}"
        )
    for one in materialised:
        if "," in one or not one.strip():
            raise ValueError(f"invalid Spotify ID: {one!r}")
    return ",".join(materialised)


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip None entries so httpx doesn't serialise them as 'None'."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class SpotifyClient:
    """Synchronous Spotify Web API client.

    Exposes typed wrappers for every read-only endpoint the MCP tools
    call. Each wrapper returns the raw JSON from Spotify so the MCP
    layer can forward ``uri`` / ``external_urls`` / ``href`` fields
    unchanged for downstream playback servers (e.g. a Sonos MCP) to
    consume.
    """

    def __init__(
        self,
        client_id: str,
        refresh_token: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 15.0,
        on_token_rotation: Callable[[str], None] | None = None,
    ) -> None:
        self._client_id = client_id
        self._refresh_token = refresh_token
        self._http = http if http is not None else httpx.Client(timeout=timeout)
        self._owns_http = http is None
        self._access: _AccessToken | None = None
        self._on_rotation = on_token_rotation

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
        """Current refresh token (may have rotated since construction)."""
        return self._refresh_token

    # ------------------------------------------------------------------
    # OAuth refresh
    # ------------------------------------------------------------------

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
        new_rt = data.get("refresh_token")
        if new_rt and new_rt != self._refresh_token:
            self._refresh_token = new_rt
            # Fire the rotation callback so callers can persist the new
            # token. Spotify rotates on every refresh response in some
            # configurations; without persistence, a deployment that
            # reads the seed from an external store (1Password, k8s
            # secret, etc.) will fail on the next process start when
            # the seed has already been invalidated by the rotation.
            if self._on_rotation is not None:
                # Persistence is best-effort: never let it break a
                # refresh that otherwise succeeded.
                with contextlib.suppress(Exception):
                    self._on_rotation(new_rt)

    def _access_token(self) -> str:
        if self._access is None or self._access.expires_at <= time.time():
            self._refresh()
        assert self._access is not None
        return self._access.value

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    def _raw_get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return self._http.get(
            f"{API_BASE}{path}",
            params=_clean(params),
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET ``{API_BASE}{path}`` with an authorised request.

        Raises :class:`SpotifyDeprecatedForNewAppsError` on 403/404 for
        endpoints Spotify restricted to old apps in November 2024;
        otherwise propagates ``httpx.HTTPStatusError``.
        """
        r = self._raw_get(path, params)
        if r.status_code in (403, 404) and any(
            seg in path for seg in _DEPRECATED_FOR_NEW_APPS_PATHS
        ):
            raise SpotifyDeprecatedForNewAppsError(
                f"Spotify returned HTTP {r.status_code} for {path}. "
                "This endpoint was restricted to pre-2024-11-27 apps. "
                "If your Spotify Developer app was created after that date, "
                "this tool will not work for you and there is no documented "
                "alternative. See "
                "https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api"
            )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def me(self) -> dict[str, Any]:
        """``GET /me`` — the authenticated user's profile."""
        return self.get("/me")

    # ------------------------------------------------------------------
    # Search & lookup
    # ------------------------------------------------------------------

    def search(
        self,
        q: str,
        types: Sequence[SearchType],
        *,
        market: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_external: str | None = None,
    ) -> dict[str, Any]:
        """``GET /search`` — universal search.

        ``types`` is one or more of ``track`` / ``artist`` / ``album`` /
        ``playlist`` / ``show`` / ``episode`` / ``audiobook``. The
        response groups results by type, each carrying ``uri`` +
        ``external_urls`` per item — the inputs a downstream playback
        MCP needs.
        """
        if not types:
            raise ValueError("at least one search type is required")
        return self.get(
            "/search",
            params={
                "q": q,
                "type": ",".join(types),
                "market": market,
                "limit": limit,
                "offset": offset,
                "include_external": include_external,
            },
        )

    def get_track(self, track_id: str, *, market: str | None = None) -> dict[str, Any]:
        """``GET /tracks/{id}`` — single-track lookup."""
        return self.get(f"/tracks/{track_id}", params={"market": market})

    def get_tracks(self, ids: Iterable[str], *, market: str | None = None) -> dict[str, Any]:
        """``GET /tracks?ids=...`` — bulk track lookup (≤ 50 IDs)."""
        return self.get(
            "/tracks",
            params={
                "ids": _join_ids(ids, limit=MAX_IDS_PER_TRACKS_LOOKUP),
                "market": market,
            },
        )

    def get_album(self, album_id: str, *, market: str | None = None) -> dict[str, Any]:
        """``GET /albums/{id}`` — album metadata + tracklist."""
        return self.get(f"/albums/{album_id}", params={"market": market})

    def get_albums(self, ids: Iterable[str], *, market: str | None = None) -> dict[str, Any]:
        """``GET /albums?ids=...`` — bulk album lookup (≤ 20 IDs)."""
        return self.get(
            "/albums",
            params={
                "ids": _join_ids(ids, limit=MAX_IDS_PER_ALBUMS_LOOKUP),
                "market": market,
            },
        )

    def get_artist(self, artist_id: str) -> dict[str, Any]:
        """``GET /artists/{id}`` — artist metadata."""
        return self.get(f"/artists/{artist_id}")

    def get_artists(self, ids: Iterable[str]) -> dict[str, Any]:
        """``GET /artists?ids=...`` — bulk artist lookup (≤ 50 IDs)."""
        return self.get(
            "/artists",
            params={"ids": _join_ids(ids, limit=MAX_IDS_PER_ARTISTS_LOOKUP)},
        )

    def get_artist_top_tracks(self, artist_id: str, *, market: str | None = None) -> dict[str, Any]:
        """``GET /artists/{id}/top-tracks`` — top tracks for an artist.

        ``market`` is optional. Pass an ISO-3166 country code (``"PL"``,
        ``"GB"``, ``"US"``, …) for region-specific top tracks. Note that
        the historic ``"from_token"`` value — which used to resolve the
        authenticated user's country automatically — was withdrawn for
        new apps on 2024-11-27 alongside the audio-features /
        recommendations restrictions, and returns 403 against new apps;
        avoid passing it.
        """
        params: dict[str, Any] = {}
        if market is not None:
            params["market"] = market
        return self.get(f"/artists/{artist_id}/top-tracks", params=params)

    def get_artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: Sequence[IncludeGroups] | None = None,
        market: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """``GET /artists/{id}/albums`` — paged discography."""
        return self.get(
            f"/artists/{artist_id}/albums",
            params={
                "include_groups": ",".join(include_groups) if include_groups else None,
                "market": market,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_playlist(
        self,
        playlist_id: str,
        *,
        market: str | None = None,
        fields: str | None = None,
        additional_types: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """``GET /playlists/{id}`` — playlist metadata + tracks."""
        return self.get(
            f"/playlists/{playlist_id}",
            params={
                "market": market,
                "fields": fields,
                "additional_types": (",".join(additional_types) if additional_types else None),
            },
        )

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """``GET /users/{id}`` — any user's public profile."""
        return self.get(f"/users/{user_id}")

    def get_audio_features(self, ids: Iterable[str]) -> dict[str, Any]:
        """``GET /audio-features?ids=...`` — bulk audio features (≤ 100 IDs).

        Restricted-for-new-apps as of 2024-11-27 (see
        :class:`SpotifyDeprecatedForNewAppsError`).
        """
        return self.get(
            "/audio-features",
            params={"ids": _join_ids(ids, limit=MAX_IDS_PER_AUDIO_FEATURES_LOOKUP)},
        )

    # ------------------------------------------------------------------
    # Library & listening (user-scoped)
    # ------------------------------------------------------------------

    def get_top(
        self,
        type_: TopType,
        *,
        time_range: TimeRange = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """``GET /me/top/{artists|tracks}`` — your top artists or tracks.

        ``time_range`` = ``short_term`` (~4 weeks) / ``medium_term`` (~6
        months) / ``long_term`` (lifetime). Items carry ``uri`` so a
        downstream playback MCP can act without a second lookup.
        """
        return self.get(
            f"/me/top/{type_}",
            params={"time_range": time_range, "limit": limit, "offset": offset},
        )

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        """``GET /me/player/recently-played`` — last ≤ 50 plays.

        Cursor params are epoch-milliseconds. The 50-track buffer is
        the constraint for the Phase 2 poller cadence — Spotify does
        not keep history beyond it.
        """
        return self.get(
            "/me/player/recently-played",
            params={"limit": limit, "before": before, "after": after},
        )

    def get_now_playing(
        self,
        *,
        market: str | None = None,
        additional_types: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """``GET /me/player/currently-playing`` — what's playing right now.

        Returns ``{}`` when nothing is playing — Spotify responds 204
        No Content in that case. Premium-only endpoint.
        """
        r = self._raw_get(
            "/me/player/currently-playing",
            params={
                "market": market,
                "additional_types": (",".join(additional_types) if additional_types else None),
            },
        )
        if r.status_code == 204:
            return {}
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def get_playback_state(
        self,
        *,
        market: str | None = None,
        additional_types: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """``GET /me/player`` — full playback state (device, shuffle, repeat).

        ``{}`` when no active device. Premium-only endpoint.
        """
        r = self._raw_get(
            "/me/player",
            params={
                "market": market,
                "additional_types": (",".join(additional_types) if additional_types else None),
            },
        )
        if r.status_code == 204:
            return {}
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def get_devices(self) -> dict[str, Any]:
        """``GET /me/player/devices`` — devices visible to this account."""
        return self.get("/me/player/devices")

    def get_playlists(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """``GET /me/playlists`` — paged list of your playlists."""
        return self.get("/me/playlists", params={"limit": limit, "offset": offset})

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> dict[str, Any]:
        """``GET /me/tracks`` — paged liked tracks (with ``added_at``)."""
        return self.get(
            "/me/tracks",
            params={"limit": limit, "offset": offset, "market": market},
        )

    def get_saved_albums(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> dict[str, Any]:
        """``GET /me/albums`` — paged saved albums (with ``added_at``)."""
        return self.get(
            "/me/albums",
            params={"limit": limit, "offset": offset, "market": market},
        )

    def get_followed_artists(
        self,
        *,
        limit: int = 20,
        after: str | None = None,
    ) -> dict[str, Any]:
        """``GET /me/following?type=artist`` — paged followed artists.

        Cursor-paginated (``after`` is an artist ID), not offset-paged.
        """
        return self.get(
            "/me/following",
            params={"type": "artist", "limit": limit, "after": after},
        )
