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
6. **News feed** — confirm the startup log line `news feed: N high-impact USD/EUR events`;
   403/429 from the feed must back off, never crash the loop.
7. **Gateway outage** — stop the gateway; on the third failed poll (~90s) expect
   `BLIND: 3 polls failed` in the log and, with `notify:` set, on Telegram; start the gateway;
   expect `sight restored after N failed polls`. No crash, no stale kill state, and exactly one
   alert each way no matter how long the outage.

Rule of thumb: if you cannot show a log line proving a layer fired, that layer does not exist.

## Executions on record
- 2026-08-31 — single-file guardian, live prop deployment (Exness demo stand-in).
- 2026-09-01 — THIS PACKAGE, v post-#3, against a live local demo (botverify) under the
  shared-account lock: startup/no-op, SOFT (position survived), HARD (package flattened a real
  0.01 position), release, STATIC (lock survived a restart; operator clear procedure), manual-kill
  respect (2 cycles, untouched), dead-gateway outage (loop survived), teardown flat. Cost: one
  0.01 round trip (~$0.50 spread). The package is drill-validated and eligible to replace the
  single-file deployment at the next maintenance window.
