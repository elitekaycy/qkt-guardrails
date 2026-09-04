# Changelog

All notable changes to qkt-guardrails. Versions are git tags (`vX.Y.Z`); each tag publishes
`ghcr.io/elitekaycy/qkt-guardrails:vX.Y.Z` and a GitHub Release.

## v0.2.0 — 2026-09-04

First release deployed on a live prop account (The5ers High Stakes 50k, bot1), replacing the
single-file guardian that had run since 2026-08-31.

### Fixed
- `ladder.friday_flat: false` could not be loaded from YAML: the config loader coerced every
  non-numeric field to text and rejected the boolean, so the only per-book weekend opt-out
  added in #4 was unusable. Booleans are now typed.
- `tests/test_loop.py` used the real wall clock and failed whenever the suite ran inside the
  weekend window. `run_once` takes an injectable `now`.

### Added
- `ladder.weekend_release_utc` (HH:MM, default `"22:10"`): the Sunday minute the WEEKEND rung
  releases. Was hard-coded; venues reopen at different times.
- `ladder.news_currencies` (default `"USD,EUR"`): which ForexFactory country codes open a
  NEWS window.
- `guardian.__version__`, logged on startup and printed by `--version`, so a deployment can
  prove which build is guarding.
- A tag-driven `release` job: the tag must match `pyproject.toml` and `__version__`, and a
  GitHub Release with generated notes is created next to the image.
- `docs/RELEASING.md`: the release and roll-out procedure.

### Changed
- README documents the WEEKEND rung as a market calendar with an account-global kill switch:
  24/7 (crypto) books run on their own account with `friday_flat: false`.

## v0.1.0 — 2026-09-01

Restructure into a tested, typed, stdlib-only package with per-account YAML config (#1),
fail-closed handling of a payload without positive equity (#2), unittest convention (#3),
per-book Friday-flat toggle (#4), blind/sight alerts (#5). Drilled live 2026-09-01.
