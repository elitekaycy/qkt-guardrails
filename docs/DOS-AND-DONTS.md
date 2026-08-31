# Dos and Don'ts — the qkt ecosystem

Hard-won rules that span [qkt](https://github.com/elitekaycy/qkt),
[qkt-insights](https://github.com/elitekaycy/qkt-insights), and this repo.
Each one was paid for. Do not relearn them.

## Risk & money

- DO size and monitor on **floating equity** — prop rules bind on equity, not closed P&L.
  A book that looks like -4% closed can be -15% equity intraday (observed live, 2026-08).
- DO keep two independent brakes: engine risk limits AND a gateway-level guardian.
- DO drill every guard path (SOFT/HARD/STATIC/kill/flatten/release) before trusting it.
- DON'T let a strategy without a hard TP/SL bracket near an equity-drawdown-ruled account
  (a runner's open giveback is invisible to closed-P&L limits).
- DON'T set a global per-order cap without checking every strategy's real lot needs
  (a 0.10-lot cap silently killed a 0.25-lot FX strategy for days — twice).
- DO respect minimum-volume behavior: the engine rejects below-min rather than rounding up.
  Sizing must clear the venue's volumeMin or the strategy trades nothing.

## Engine (qkt)

- DO give every strategy its own broker profile + magic number; shared magics make
  broker-side attribution guesswork.
- DO expect the promotion gate: production deploys need record+approve, and any file edit
  changes the hash and requires re-approval. This is a feature; never waive it casually.
- DO match expected_leverage / login / server / trade_mode to the account — the daemon
  refuses identity mismatches by design.
- DON'T deploy right after an mt5-gateway restart: bar history backfills for 1-3 minutes
  and warmup prefetch fails with "time-base mismatch". Wait, then deploy.
- DO remember every deploy re-arms the measured-usage ramp (entries cap 0.01 lots for 24h).

## Observability (qkt-insights)

- DO dedupe broker deals per (instance, deal_ticket): every broker profile polling the same
  account stores a copy of each deal; naive sums multiply P&L by the profile count.
- DON'T join on broker_order_id (it repeats across profiles and fans rows out); use scalar
  subselects.
- DO verify dashboard numbers against gateway deal history before trusting them
  (monthly-chunked history_deals_range; MT5 server timestamps may be UTC+2/+3).

## Operations

- DO take the armed-run lock before manual orders on a shared account:
  flock /var/tmp/qkt-validation/LIVE-LOCK-<server>-<login>.
- DO keep gateways loopback-bound; expose only dashboards, and put real-money dashboards
  behind HTTPS with unique passwords.
- DON'T edit guardian state while it runs (30s save loop overwrites you): stop, edit, start.
