"""Preview: composing Phase 1 tools with a Sonos playback MCP.

This file is **not runnable today** — Phase 1 hasn't shipped the tools
yet. It's an illustrative sketch of the intended composition pattern so
you can see what the API will look like, and so reviewers can sanity-
check the design before the real implementation lands.

The agent flow modelled here:

    1. Get the user's top artist this week.
    2. Get that artist's top tracks.
    3. Hand the resulting Spotify URI to a Sonos MCP's ``play`` tool.

Every tool here returns Spotify ``uri`` and ``external_urls`` fields
verbatim, which is what makes the hand-off to the playback MCP zero-copy.

Run (once Phase 1 lands)::

    python examples/03_phase1_preview.py
"""

from __future__ import annotations

# ----- Phase 1 imports (don't exist yet) -----
# from spotify_wrapped_mcp.tools import get_artist_top_tracks, get_top
# from your_sonos_mcp import play


def main() -> int:
    raise NotImplementedError(
        "Phase 1 not yet implemented. This file is a design sketch — see "
        "docs/ARCHITECTURE.md for the planned tool surface."
    )

    # ---- Sketch of what the Phase 1 / composition flow will look like ----
    #
    # top = get_top(type="artists", time_range="short_term", limit=1)
    # top_artist = top["items"][0]
    # print(f"Top artist this week: {top_artist['name']}")
    #
    # tracks = get_artist_top_tracks(artist_id=top_artist["id"], market="from_token")
    # top_track = tracks["tracks"][0]
    # print(f"  Top track: {top_track['name']}  ({top_track['uri']})")
    #
    # # Hand off to the Sonos MCP — note the URI is passed straight through.
    # play(uri=top_track["uri"], room="living-room")


if __name__ == "__main__":
    raise SystemExit(main())
