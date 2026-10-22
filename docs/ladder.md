# The ladder

The guardian reads floating account equity every poll and walks this ladder top-down. The
decision logic is pure (`guardian/ladder.py`, no I/O); every rung and every transition between
rungs is covered by `tests/test_ladder.py`. STATIC always wins if triggered, even during a
WEEKEND or NEWS window.

| Layer | Trigger (`ladder:` in config) | Action |
|---|---|---|
| STATIC | equity ≤ initial − `static_pct`% | kill + flatten, **locked** until an operator clears it |
| HARD | daily equity loss ≥ `hard_pct` of prev-day close | kill + **flatten everything**; auto-clears at the firm's day roll (`roll_utc_hour`, or `roll_local_hour` in `roll_tz`) |
| SOFT | daily equity loss ≥ `soft_pct` of prev-day close | kill switch on, no new orders; open brackets keep managing |
| WEEKEND | Fri `fri_flat_utc`:00 UTC, only when `friday_flat: true` | kill + flatten; releases Sun `weekend_release_utc` (default 22:10) |
| NEWS | inside any event window: ±`news_pad_min` min around a high-impact release for `news_currencies` (default USD,EUR; ForexFactory), or the whole session of a bank holiday when `news_include_holidays: true` | kill on, auto-release after |

The day roll is when "today" starts for SOFT and HARD: the previous day's close is the equity at
that moment. A firm whose server day follows daylight saving (The5ers: midnight server time =
17:00 New York; FTMO: midnight Prague) sets `roll_tz` and `roll_local_hour` so the roll stays at
the firm's midnight all year; a fixed `roll_utc_hour` is an hour off for half of it. The day is
named by the date it began on in that timezone, so moving a summer 21:00 UTC roll to 17:00 New
York keeps the same day names and does not roll the day on restart.

The guardian releases only a kill switch it engaged itself. A kill an operator engaged by hand
stays on until the operator releases it.

## The WEEKEND rung is a market calendar, not a risk rule

It exists for instruments that **close** over the weekend (FX, metals, indices), where a gap
jumps venue stops at the reopen. The kill switch is **account-global**: it blocks every new
order on the account and `flatten` closes every position, so it can never be applied to some
symbols and not others. That gives one hard rule:

- A book trading **24/7 instruments (crypto)** runs on its **own account** with
  `friday_flat: false`. Session handling for those symbols belongs to the engine's per-symbol
  market-data calendar, not to the guardian.
- Never mix weekend-closing and 24/7 instruments on one guarded account: either the crypto
  book gets flattened every Friday, or the FX book carries weekend gap risk unguarded.
- `weekend_release_utc` is your venue's first tradable Sunday minute (Exness and IC Markets
  reopen about 22:05 UTC, The5ers 22:10). Too early and the engine sees a 423 storm; too late
  and you miss the open.
- `weekend_exclude` (v0.5.0) names symbols that keep trading through the weekend. Naming any
  switches the rung to WEEKEND-PARTIAL: it closes every other open position, does not engage
  the kill switch, and re-runs every poll. The equity rungs ignore exclusions.

## Alerts and blindness

With `notify:` set, the guardian sends a Telegram message on every engage and release. It also
reports the one failure the ladder cannot see: `blind_after_failures` straight failed polls
(default 3) means the guardian is **blind**, not watching equity at all. It says so once, and
again when sight returns.

## Presets

Threshold sets sized *inside* each firm's rules, so the guardian trips before the firm does.
Copy one from `examples/` into `configs/<account-name>.yaml` and fill in `target` and `account`.

| preset | firm rule (daily/total) | SOFT / HARD / STATIC |
|---|---|---|
| `the5ers-high-stakes` | 5% / 10% static | 2.5 / 3.5 / 6 |
| `the5ers-hyper-growth` | 3% / 6% static | 1.5 / 2.2 / 4 |
| `ftmo` | 5% / 10% static | 2.5 / 3.5 / 6 |
