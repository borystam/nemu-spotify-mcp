# Contributing

Thanks for your interest. This project is small and aims to stay that way —
a focused, read-only Spotify analytics MCP server.

## Development setup

```bash
git clone https://github.com/borystam/spotify-wrapped-mcp
cd spotify-wrapped-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running checks

The CI pipeline runs each of these; you can run them locally too.

```bash
ruff check .
black --check .
isort --check-only .
mypy src
pytest --cov=spotify_wrapped_mcp --cov-report=term-missing
```

The same commands also run via `pre-commit run --all-files`.

## Tests

- **Unit tests** live in `tests/` and must not hit the real Spotify API.
  Use `httpx.MockTransport` (preferred — already a dep via httpx) or
  `respx` to stub responses.
- **Integration tests** are gated by `SPOTIFY_INTEGRATION_TESTS=1`. They
  require valid credentials at `~/.config/spotify-wrapped-mcp/credentials.json`
  and **will** hit Spotify's API. Skip them in PRs unless you're testing a
  bug that only reproduces against a real account.
- **Property tests** (Hypothesis) are encouraged for anything that takes
  user input (e.g. ID list lengths, time-range strings).
- **Snapshot tests** (`syrupy`) protect the shape of `get_wrapped`'s output
  against accidental breakage.

## Style

- **Conventional Commits** for commit messages (`feat:`, `fix:`, `docs:`,
  `test:`, `chore:`, `ci:`, `refactor:`). One logical change per commit.
- **Black + isort** for formatting. **Ruff** for linting. **Mypy --strict**
  for type-checking. Pre-commit enforces all four.
- Public functions and classes are typed. `Any` is allowed only at the
  boundary with `mcp.*` and the parsed Spotify JSON payloads, where we
  haven't yet typed the response schemas.

## Privacy / security

- **Never** commit real Spotify data. The repo's tests use the placeholder
  user `alice_example` and synthetic IDs.
- **Never** commit secrets. The `.gitignore` already covers
  `credentials.json`, `*.env`, `tokens.json`, and friends; if you add a
  new secrets file format, add it there too.
- Token handling: refresh tokens stay on disk at `0600`. Access tokens are
  cached in memory only and expire after 1 hour.

## Reporting bugs

Use the issue template. Include:
- The exact command + output (redact `client_id`, `display_name`, tokens).
- Python version and OS.
- Whether the error reproduces with `--no-browser`.

## Releases

Maintainers tag a release with `git tag vX.Y.Z` after bumping the version
in `pyproject.toml` and updating `CHANGELOG.md`. The CI build job verifies
the sdist + wheel are healthy; publishing to PyPI is manual until further
notice.
