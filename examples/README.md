# Examples

Short, runnable scripts demonstrating common patterns with
``spotify-wrapped-mcp``. All examples assume you've already authorised
once via ``spotify-wrapped-mcp-auth``.

| File                          | What it shows                                                            |
| ----------------------------- | ------------------------------------------------------------------------ |
| `01_smoke_test.py`            | Load credentials, call ``GET /me`` programmatically, print the profile. |
| `02_inspect_credentials.py`   | Read the credentials file safely (no secrets printed).                  |
| `03_phase1_preview.py`        | Illustrative sketch of how the Phase 1 tools will compose with a       \
|                               | playback MCP (Sonos). **Not runnable today** — commented-out.            |

Run any of them with:

```bash
python examples/01_smoke_test.py
```

These scripts deliberately avoid printing anything that could identify
the user's Spotify account (no `display_name`, `id`, or token bytes).
They are safe to share when filing bug reports.
