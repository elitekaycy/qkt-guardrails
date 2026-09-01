# Repository Instructions

This file is the root instruction file for automated coding work in this
repository. Keep it synchronized with `CLAUDE.md`; this file is the concise
always-read version.

## Working Style

- Be direct and pragmatic. Call out wrong assumptions or risky requests with reasons.
- Make the smallest reasonable change that actually solves the problem.
- Prefer simple, readable, maintainable code over clever code.
- Match surrounding style exactly.
- Fix bugs found while working when they are in scope.
- Do not rewrite or throw away existing implementations without explicit approval.

## Safety Rules (this repo guards live accounts)

- Never weaken thresholds, presets, or guard logic without stating why in the
  commit and re-running drills/PLAYBOOK.md.
- Fail closed: ambiguity means kill switch ON.
- Engine-independent forever: gateway API only; stdlib only; no engine imports.
- One guardian process per account. Never merge accounts into one process/config —
  a bug or hang watching one account must never delay another's kill decision.
- Guardian state is edited only while the guardian is stopped.
- See docs/DOS-AND-DONTS.md for rules that span the whole qkt ecosystem.

## Working in this codebase

- `guardian/ladder.py` is pure (no I/O, `now`/`equity`/`news` passed in) — that's what makes
  it unit-testable. Keep new decision logic there and pure; keep gateway/state/notify I/O out.
- Every behavior change to the ladder needs a test in `tests/test_ladder.py` before it needs
  a drill — the drill proves the deployed binary; the test proves the logic won't regress.
- Config is YAML, one file per account (`guardian/config.py`, `guardian/simpleyaml.py`).
  Non-secret fields (`target.name`, `gateway_url`, `initial_balance`) are literal in the file;
  only secrets use `${VAR}` interpolation — don't move non-secrets behind env vars, it breaks
  multiple accounts sharing one `.env`.
- Before committing: `python -m ruff check guardian tests`, `python -m mypy`,
  `python -m unittest discover -s tests`. CI runs the same three plus a Docker smoke test.
