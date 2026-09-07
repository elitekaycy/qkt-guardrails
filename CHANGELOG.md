# Changelog

All notable changes to qkt-guardrails. Versions are git tags (`vX.Y.Z`); each tag publishes
`ghcr.io/elitekaycy/qkt-guardrails:vX.Y.Z` and a GitHub Release.

## v0.4.0 — 2026-09-07

### Added
- **Hub journal news source.** `ladder.news_hub_root` reads NEWS-rung event windows from a
  qkt-data-hub store on disk instead of fetching the ForexFactory feed, removing the only
  outbound network call the brake makes. A stale hub heartbeat is treated as a failed fetch, so
  the cache keeps its last known windows rather than concluding no release is coming; a missing
  heartbeat, a missing journal or an unreadable file fail the same way.
  `ladder.news_hub_stale_after_seconds` sets the threshold (default 900). Off by default: without
  `news_hub_root` the HTTP source is constructed exactly as before. Not yet drilled against a hub
  store on a real account; add that to `drills/PLAYBOOK.md` before enabling it there.

## v0.3.0 — 2026-09-06

Deployed to bot1 (The5ers High Stakes 50k) 2026-09-06 10:35 UTC, config unchanged.

### Fixed
- The ForexFactory fetch ran on the guard loop, between reading equity and reading the kill
  switch: on a refresh cycle a hung feed could stretch one cycle to ~70s before the sleep. A
  safety daemon must not have a third-party HTTP call on its critical path. Fetching now runs
  on a daemon thread; `windows()` never blocks.
- A failed fetch and a successful one shared one timer, so a feed outage at startup left the
  NEWS rung unarmed for a full hour. Failure now retries on `news_retry_seconds` (default 300).
- A bank holiday was a five-minute window at midnight. With `news_include_holidays: true` it
  is now the whole calendar day in the feed's own offset — the row is stamped 00:00 with no
  duration, and the hazard is the session.
- Several releases at the same minute (CPI m/m + y/y + core) produced duplicate windows and an
  inflated log count. Windows are de-duplicated.
- A naive `date` (no UTC offset) was read as host-local time and would have shifted a window
  by the New York offset. It is now rejected as malformed.
- An unknown config key (`soft_pcnt: 1`) silently left the real key at its default. It is now
  a load-time error.

### Changed
- `guardian/news.py` is a source seam: `Source.fetch() -> list[Event]`, each `Event` carrying
  its own `(start, end)` window, `NewsCache` over any number of sources with independent
  backoff and merged windows. The ladder consumes windows (`is_in_news_window(now, windows)`)
  and no longer knows about pads or providers. Adding a provider is a new transformer.
- Startup log line now also reports `poll=`, `timeout=`, `blind_after=`; the news line reads
  `news[forexfactory]: N window(s) this week`.

### Added
- Every runtime constant is configurable, each defaulting to its previous hard-coded value:
  `poll.gateway_timeout_seconds` (20), `poll.blind_after_failures` (3), `health.stale_cycles`
  (3), `notify.telegram_timeout_seconds` (10), `ladder.news_timeout_seconds` (30),
  `ladder.news_refresh_steady_seconds` (21600), `ladder.news_retry_seconds` (300),
  `ladder.news_include_holidays` (false).
- Load-time validation that an explicit `poll.gateway_timeout_seconds` does not exceed
  `poll.interval_seconds` — a 10s poll with a 20s timeout is not a 10s poll. Unset, the
  timeout is `min(20, interval_seconds)`, so a config with a short poll keeps starting after
  the upgrade instead of being refused for a value it never wrote.

## v0.2.0 — 2026-09-04

First release deployed on a live prop account (The5ers High Stakes 50k, bot1), replacing the
single-file guardian that had run since 2026-08-31.

### Fixed
- The image's non-root user could not write the `/state` volume it declares: without a
  pre-chowned bind mount every poll logged `loop error: Permission denied` and no state was
  ever saved. `/state` is now created and owned by the fixed uid 10001 in the image, and the
  CI smoke test fails on any `loop error`.
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
