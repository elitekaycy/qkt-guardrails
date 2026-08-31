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
- Guardian state is edited only while the guardian is stopped.
- See docs/DOS-AND-DONTS.md for rules that span the whole qkt ecosystem.
