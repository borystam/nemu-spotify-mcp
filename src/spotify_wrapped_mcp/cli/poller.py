"""``spotify-history-poller`` — Phase 2 stub.

The poller will append the user's recently-played tracks to a local
JSONL file when invoked (intended for cron / systemd-timer use). The
implementation lands in Phase 2; this stub exits non-zero with a clear
message so callers don't silently no-op.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print(
        "spotify-history-poller is not implemented yet (planned for Phase 2). "
        "Track progress at "
        "https://github.com/borystam/spotify-wrapped-mcp/issues",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
