<h1 align="center">[qkt]/guardrails</h1>

<h3 align="center">An engine-independent equity watchdog for prop-firm and live accounts running the <a href="https://github.com/elitekaycy/qkt">qkt</a> trading engine — or any MT5 strategy behind an <a href="https://github.com/elitekaycy/mt5-gateway">mt5-gateway</a>.</h3>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="license"></a>
  <img src="https://img.shields.io/badge/status-skeleton-orange.svg" alt="status">
  <img src="https://img.shields.io/badge/python-3.12%20stdlib%20only-3776AB?logo=python&logoColor=white" alt="python">
</p>

---

> Sibling project of [qkt](https://github.com/elitekaycy/qkt) and [qkt-insights](https://github.com/elitekaycy/qkt-insights) — same brand, same engineering style.

**qkt-guardrails** is the outer brake. Your strategy engine already has risk limits — but those
live *inside the process being guarded*. If the engine hangs, leaks, or hits the one bug you
didn't test, its risk layer hangs with it. The guardian is a separate ~150-line process that
watches one signal the engine's realized-P&L halts cannot see — **floating account equity, the
number prop-firm rules actually bind on** — and enforces limits at the broker-gateway layer via
a kill switch that works even when the engine doesn't.

The design promise: **two independent brakes.** The guardian knows nothing about your engine.
It speaks only to the gateway. If everything else fails, it still flattens.

```
strategy engine (qkt, EA, anything) ──▶ mt5-gateway ──▶ MT5 ──▶ broker
                                          ▲   ▲
                     kill switch / flatten │   │ equity poll (30s)
                                          [guardian]
                                    state: /state/guardian.json
```

## The ladder

| Layer | Trigger (env-tunable) | Action |
|---|---|---|
| SOFT | daily equity loss ≥ `SOFT_PCT` of prev-day close | kill switch on — no new orders; open brackets keep managing |
| HARD | ≥ `HARD_PCT` | kill + **flatten everything**; auto-clears at the firm's day roll (`ROLL_UTC_HOUR`) |
| STATIC | equity ≤ initial − `STATIC_PCT`% | kill + flatten, **locked** until an operator clears it |
| NEWS | ±`NEWS_PAD_MIN` min around high-impact USD/EUR events (ForexFactory feed) | kill on, auto-release after |
| FRIDAY | Fri `FRI_FLAT_UTC`:00 UTC | kill + flatten; releases Sun 22:10 UTC |

Telegram alerts on every engage/release (optional, `TG_TOKEN`/`TG_CHAT`).

## Quick start

```bash
cp .env.example .env            # gateway URL/key, account size, pick a preset
cat presets/the5ers-high-stakes.env >> .env
docker compose -f docker-compose.example.yml up -d guardian
```

Then **run the drills** (`drills/PLAYBOOK.md`) before you trust it with money. A guardrail you
have not fired is a decoration.

## Presets

Threshold sets sized *inside* each firm's rules — the guardian must trip before the firm does:

| preset | firm rule (daily/total) | SOFT / HARD / STATIC |
|---|---|---|
| `the5ers-high-stakes` | 5% / 10% static | 2.5 / 3.5 / 6 |
| `the5ers-hyper-growth` | 3% / 6% static | 1.5 / 2.2 / 4 |
| `ftmo` | 5% / 10% static | 2.5 / 3.5 / 6 |

## Status

Skeleton release, extracted from a live prop-rehearsal deployment (acceptance-drilled
2026-08-31: live fill + kill/flatten round trip, SOFT/HARD/STATIC threshold drills, restart
recovery, news feed live). Battle scars and a hardening roadmap will land here as the
rehearsal accumulates history.
