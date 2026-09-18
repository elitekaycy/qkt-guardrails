# Drill playbook

Run ALL of these before trusting the guardian with money, and after any change to guard
logic or thresholds. All verified live 2026-08-31 on a demo account.

1. **Kill-switch round trip** — place a minimum-lot order with SL/TP via the gateway,
   `POST /kill?flatten=true`, verify the position closes at market, verify a new order is
   rejected 423 while killed, `POST /kill/release`.
2. **SOFT** — stop guardian; set `prev_close` in the state file (`state.path` in the
   account's config, default `/state/guardian.json`) so today's equity reads as a loss
   between SOFT and HARD; start; expect `KILL engaged (DAILY-SOFT)` with no flatten.
   Restore state; expect release.
3. **HARD** — same, loss above HARD; expect kill + flatten (re-)issued.
4. **STATIC** — set `static_pct: -1` temporarily in the account's YAML config (floor above
   equity); expect `KILL engaged (STATIC)` + flatten + the lock SURVIVING guardian
   restarts. Recover with the operator procedure: stop → set `"lock": null` in state →
   start.
5. **Manual-kill respect** — engage the kill switch by hand; verify the guardian does NOT
   release it (it only releases kills it engaged).
6. **News feed** — confirm the log line `news[forexfactory]: N window(s) this week` (with `news_include_holidays: true`, a bank-holiday week shows a 1440-minute window);
   403/429 from the feed must back off, never crash the loop.
7. **Gateway outage** — stop the gateway; on the third failed poll (~90s) expect
   `BLIND: 3 polls failed` in the log and, with `notify:` set, on Telegram; start the gateway;
   expect `sight restored after N failed polls`. No crash, no stale kill state, and exactly one
   alert each way no matter how long the outage.

8. **Version** — the first log line after start reads `guardian[<name>] v<X.Y.Z> up:` with the
   version you meant to deploy. Wrong version = wrong binary; stop.

Rule of thumb: if you cannot show a log line proving a layer fired, that layer does not exist.

## Executions on record
- 2026-08-31 — single-file guardian, live prop deployment (Exness demo stand-in).
- 2026-09-01 — THIS PACKAGE, v post-#3, against a live local demo (botverify) under the
  shared-account lock: startup/no-op, SOFT (position survived), HARD (package flattened a real
  0.01 position), release, STATIC (lock survived a restart; operator clear procedure), manual-kill
  respect (2 cycles, untouched), dead-gateway outage (loop survived), teardown flat. Cost: one
  0.01 round trip (~$0.50 spread). The package is drill-validated and eligible to replace the
  single-file deployment at the next maintenance window.
- 2026-09-04 — v0.2.0 image (`qkt-guardrails:dev`, same tree as the tag), against the local demo
  gateway (botverify, Exness-MT5Trial9 436804390) under the shared-account lock, market closed
  (Friday 22:12-22:15 UTC), no positions open: version line (drill 8), no-op startup, SOFT engage
  → release on restored equity, HARD engage+flatten → held with equity restored while the daily
  lock stood → released once the lock cleared as the day roll does, STATIC engage+flatten → lock
  survived a restart → STATIC-HOLD with the floor back below equity → released only after the
  operator cleared `lock` → manual-kill respect (kill engaged by hand, guardian left it alone),
  WEEKEND engage (friday_flat: true inside the window) and release (friday_flat: false), BLIND on
  a dead port after exactly 3 polls. Kill switch left released, venue untouched. Drill 1 (order
  round trip through kill+flatten) needs an open market: scheduled for the Sunday 22:10 UTC open
  on the deployed bot1 instance.
- 2026-09-18 — WEEKEND-PARTIAL (`ladder.weekend_exclude`), against the local demo gateway
  (botverify, Exness-MT5Trial9 436804390) under the shared-account lock, market open
  (Friday 12:40 UTC). Opened two real positions, BTCUSDm (3250382665) and XAUUSDm
  (3250382750), then ran `GatewayClient.flatten_except(("BTCUSDm",))`: it closed XAUUSDM
  only, BTCUSDm stayed open, and the kill switch was never engaged (`kill_switch_active`
  false throughout). Cleaned up to flat. Unit side: 125 tests green, including that STATIC,
  DAILY-HARD and DAILY-SOFT inside the weekend window still return `want_kill` with
  `spare_symbols` empty — an equity rung can never be talked out of closing something.
  Then the released v0.5.0 IMAGE itself, same account under the same lock, market open
  (Friday 12:43 UTC), `fri_flat_utc: 6` to put the window live and `initial_balance` pinned to
  the demo's equity so no equity rung could fire: opened BTCUSDm (3250433975) and XAUUSDm
  (3250434120), ran the real container for 25s at `poll: 10`, and it logged
  `WEEKEND-PARTIAL: closed 1 position(s) [XAUUSDM], sparing BTCUSDM`. XAUUSDm gone, BTCUSDm
  still open, `kill_switch_active` false after, cleaned up to flat.
  Rolled bot1 12:44 UTC (`v0.3.0` -> `v0.5.0`): `v0.5.0 up`, weekend window read as
  `Fri20:00->Sun22:10UTC`, `weekend_exclude` loaded as `('BTCUSD',)` inside the running
  container, state carried (`fri_flat: 2026-09-11`, `guard_kill: false`), container healthy,
  kill switch untouched, and all three live positions (2x XAUUSD, 1x BTCUSD) left alone --
  correct, the window does not open until 20:00 UTC.
  Not re-drilled (unchanged by this commit): SOFT/HARD/STATIC engage-release on the deployed
  image, manual-kill respect, BLIND — last proven 2026-09-04/06. Drill 1 (order round trip
  through kill+flatten) still wants the Sunday 22:10 UTC open on bot1. First live
  WEEKEND-PARTIAL on the prop account is due 2026-09-18 20:00 UTC: expect the two XAUUSD legs
  closed and the BTCUSD short left open.

- 2026-09-06 — v0.3.0 image (`ghcr.io/elitekaycy/qkt-guardrails:v0.3.0`, the exact tag rolled),
  against the local demo gateway (botverify, Exness-MT5Trial9 436804390) under the shared-account
  lock, market closed (Sunday 10:34 UTC), no positions open, with bot1's live config verbatim
  except gateway URL, `initial_balance` pinned to the demo's equity (no rung can fire),
  `friday_flat: false` (Sunday), `news_include_holidays: true` (to exercise the new path):
  version line with the new `poll=/timeout=/blind_after=` fields (drill 8), config loaded through
  the new unknown-key/timeout validation, `news[forexfactory]: 5 window(s) this week` including
  the 1440-minute Labor Day window, healthcheck rc=0, state file written by uid 10001, kill
  switch untouched (`false` after), no loop error/BLIND/traceback. Then bot1's file verbatim
  through the v0.3.0 loader: loads. Rolled bot1 10:35 UTC: `v0.3.0 up`, 4 windows (holidays off
  there), state carried (`guard_kill: true`, `fri_flat: 2026-09-04`), container healthy, weekend
  kill still engaged on the gateway. Not drilled this time (ladder rungs unchanged since v0.2.0
  except NEWS window shape): SOFT/HARD/STATIC/manual-kill/BLIND — last proven 2026-09-04. Drill 1
  (order round trip) still needs an open market: Sunday 22:10 UTC open on bot1.

