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
7. **Gateway outage** — restart the gateway; guardian logs connection errors and recovers;
   no crash, no stale kill state.

Rule of thumb: if you cannot show a log line proving a layer fired, that layer does not exist.
