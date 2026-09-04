# Releasing and rolling out

The guardian guards real money, so a release is a *procedure*, not a push.

## 1. Change lands on `main` through a PR

CI (`ci.yml`) runs on every PR: `ruff`, `mypy --strict`, `unittest`, and a Docker smoke test
that boots the image against a fake gateway. A change to `guardian/ladder.py` needs a test in
`tests/test_ladder.py`; a change to any threshold, preset, or rung needs the reason in the
commit message (see `CLAUDE.md`).

Merging to `main` publishes `ghcr.io/elitekaycy/qkt-guardrails:latest` and `:sha-<short>`.
**Nothing real runs `:latest`.**

## 2. Cut the version

1. Bump `version` in `pyproject.toml` and `__version__` in `guardian/__init__.py` (same value).
2. Add the section to `CHANGELOG.md`.
3. Merge, then tag the merge commit: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The `release` job refuses a tag that does not match both version strings, then publishes
`ghcr.io/elitekaycy/qkt-guardrails:vX.Y.Z` (with provenance and SBOM) and a GitHub Release
with generated notes.

## 3. Drill the build you are about to deploy

Run `drills/PLAYBOOK.md` against a demo gateway **with the exact image tag** you are about to
roll. Record the execution in the playbook's "Executions on record". The drills that need an
open market (the kill/flatten round trip on a real position) run in the first session after
the roll if the market is closed at release time; the state-file drills (SOFT/HARD/STATIC,
manual-kill respect, blind/sight) run any time.

## 4. Roll out

Per account, in its stack:

```yaml
guardian:
  image: ghcr.io/elitekaycy/qkt-guardrails:vX.Y.Z
  volumes:
    - ./guardian/<account>.yaml:/config/guardian.yaml:ro
    - ./guardian-state:/state
```

The state file (`/state/guardian.json`) is forward-compatible across versions: unknown keys
are ignored, missing keys take defaults. Rolling during an engaged kill (weekend, news) is
safe: the new process re-evaluates the ladder on its first poll and keeps the switch it finds
engaged if the rung still applies (`guard_kill` is carried in the state file).

After the roll, the first log line must read `guardian[<name>] vX.Y.Z up: ...` — if it does
not say the version you meant to ship, you did not ship it.

## 5. Record it

`CHANGELOG.md` gets the deployment date; the account's ops repo gets the compose change; the
playbook gets the drill execution.
