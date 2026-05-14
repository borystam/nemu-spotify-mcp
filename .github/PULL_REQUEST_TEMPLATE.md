<!--
Thanks for the PR! Please keep titles in Conventional-Commits style:
feat:, fix:, docs:, test:, chore:, ci:, refactor:.
-->

## Summary

<!-- 1-3 bullet points describing what this PR changes and why. -->

## Test plan

- [ ] `ruff check .` clean
- [ ] `black --check .` clean
- [ ] `mypy src` clean (strict)
- [ ] `pytest` passes locally
- [ ] (if applicable) Manual smoke test: `spotify-wrapped-mcp test` returns 200
- [ ] (if applicable) Integration tests pass with `SPOTIFY_INTEGRATION_TESTS=1`

## Privacy / security checklist

- [ ] No real Spotify tokens, client IDs, or personal listening data in
      the diff (including test fixtures, screenshots, examples).
- [ ] No new files matching `credentials.json`, `*.env`, `tokens.json`,
      `*.history.jsonl`, or similar.
- [ ] If a new scope is requested, it is documented in `README.md` with a
      one-line justification.
