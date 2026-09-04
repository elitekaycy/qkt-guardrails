<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/qkt-guardrails-logo-dark.svg">
    <img alt="qkt-guardrails" src="docs/assets/qkt-guardrails-logo-light.svg" width="440">
  </picture>
</p>

<h3 align="center">An engine-independent equity watchdog for prop-firm and live accounts running the <a href="https://github.com/elitekaycy/qkt">qkt</a> trading engine — or any MT5 strategy behind an <a href="https://github.com/elitekaycy/mt5-gateway">mt5-gateway</a>.</h3>

<p align="center">
  <a href="https://github.com/elitekaycy/qkt-guardrails/actions/workflows/ci.yml"><img src="https://github.com/elitekaycy/qkt-guardrails/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="license"></a>
  <a href="https://github.com/elitekaycy/qkt-guardrails/pkgs/container/qkt-guardrails"><img src="https://img.shields.io/badge/ghcr.io-qkt--guardrails-2496ED?logo=docker&logoColor=white" alt="container"></a>
  <img src="https://img.shields.io/badge/python-3.12%20stdlib%20only-3776AB?logo=python&logoColor=white" alt="python">
</p>

---

> Sibling project of [qkt](https://github.com/elitekaycy/qkt) and [qkt-insights](https://github.com/elitekaycy/qkt-insights) — same brand, same engineering style.

**qkt-guardrails** is the outer brake. Your strategy engine already has risk limits — but those
live *inside the process being guarded*. If the engine hangs, leaks, or hits the one bug you
didn't test, its risk layer hangs with it. The guardian is a small, independent process that
watches one signal the engine's realized-P&L halts cannot see — **floating account equity, the
number prop-firm rules actually bind on** — and enforces limits at the broker-gateway layer via
a kill switch that works even when the engine doesn't.

The design promise: **two independent brakes.** The guardian knows nothing about your engine.
It speaks only to the gateway. If everything else fails, it still flattens.

```
strategy engine (qkt, EA, anything) ──▶ mt5-gateway ──▶ MT5 ──▶ broker
                                          ▲   ▲
                     kill switch / flatten │   │ equity poll (30s)
                                     [guardian: bot2-forward-bench]
                                    config: configs/bot2-forward-bench.yaml
                                    state:  /state/guardian.json (own volume)

                     ...one isolated guardian container per account...
```

**One process per account, on purpose.** A guardian never watches more than one account: a
hang or bug in one account's poll loop must never delay the kill decision for another. Each
container reads one YAML config that names *which* gateway/account it watches — see
[Configuration](#configuration).

## Features

- **The ladder** — SOFT / HARD / STATIC / NEWS / FRIDAY, see below. Pure, unit-tested decision
  logic (`guardian/ladder.py`) with zero I/O — every rung and every transition between rungs is
  covered by `tests/test_ladder.py`.
- **Zero runtime dependencies.** Python 3.12 stdlib only, including the YAML config loader
  (`guardian/simpleyaml.py`) — a deliberate supply-chain choice for a kill-switch. See
  [Why no PyYAML?](#why-no-pyyaml).
- **Config as data.** One YAML file per account, named after the qkt/mt5 instance it watches;
  secrets stay in `${VAR}` env references, never in the file.
- **Crash-safe state.** Atomic writes (`guardian/state.py`), so a container restart never loses
  today's rollover anchor, the static lock, or which kill switch it owns.
- **Docker-first.** One small `python:3.12-slim` image, non-root user, a `HEALTHCHECK` that
  actually checks liveness (state-file freshness, not just "process is running"), pushed to
  GHCR on every tag.
- **Typed, tested, linted.** `mypy --strict` and `ruff` clean; `guardian/gateway.py`,
  `guardian/config.py`, and `guardian/state.py` all have dedicated test files.

## The ladder

| Layer | Trigger (`ladder:` in config) | Action |
|---|---|---|
| SOFT | daily equity loss ≥ `soft_pct` of prev-day close | kill switch on — no new orders; open brackets keep managing |
| HARD | ≥ `hard_pct` | kill + **flatten everything**; auto-clears at the firm's day roll (`roll_utc_hour`) |
| STATIC | equity ≤ initial − `static_pct`% | kill + flatten, **locked** until an operator clears it |
| NEWS | ±`news_pad_min` min around high-impact events for `news_currencies` (default USD,EUR; ForexFactory feed) | kill on, auto-release after |
| WEEKEND | Fri `fri_flat_utc`:00 UTC, only when `friday_flat: true` | kill + flatten; releases Sun `weekend_release_utc` (default 22:10) |

Layers are evaluated top-down; STATIC always wins if triggered, even during a WEEKEND or NEWS
window.

### The WEEKEND rung is a market calendar, not a risk rule

It exists for instruments that **close** over the weekend (FX, metals, indices), where a gap
jumps venue stops at the reopen. The kill switch is **account-global** — it blocks every new
order on the account and `flatten` closes every position — so it can never be applied to some
symbols and not others. That gives one hard rule:

- A book trading **24/7 instruments (crypto)** runs on its **own account** with
  `friday_flat: false`. Session handling for those symbols belongs to the engine's per-symbol
  market-data calendar, not to the guardian.
- Never mix weekend-closing and 24/7 instruments on one guarded account: either the crypto
  book gets flattened every Friday, or the FX book carries weekend gap risk unguarded.
- `weekend_release_utc` is your venue's first tradable Sunday minute (Exness/IC Markets
  reopen ~22:05 UTC, The5ers 22:10). Too early and the engine sees a 423 storm; too late
  and you miss the open. Telegram alerts on every engage/release (optional, `notify:` in config), and on the one
failure the ladder cannot see: three straight failed polls means the guardian is **blind** — it
is not watching equity at all — so it says so, once, and again when sight returns.

## Quick start

```bash
cp .env.example .env                                    # one API-key var per account
cp examples/the5ers-high-stakes.yaml configs/bot2-forward-bench.yaml
$EDITOR configs/bot2-forward-bench.yaml                  # target.name, gateway_url, account size
$EDITOR docker-compose.example.yml                       # add a service block for this config
$EDITOR .env                                              # set the API key var the config references
docker compose -f docker-compose.example.yml up -d
```

Then **run the drills** (`drills/PLAYBOOK.md`) before you trust it with money. A guardrail you
have not fired is a decoration.

## Configuration

One YAML file per account (`configs/<account-name>.yaml`, gitignored — never commit real
values). `${VAR}` in any string is substituted from the environment at load time:

```yaml
target:
  name: bot2-forward-bench       # matches the qkt-insights instance_id, if any
  gateway_url: http://mt5-gateway:5001
  api_key: ${GUARDIAN_BOT2_FORWARD_BENCH_API_KEY}

account:
  initial_balance: 50000

ladder:
  soft_pct: 2.5
  hard_pct: 3.5
  static_pct: 6
  roll_utc_hour: 21
  friday_flat: true              # false for a 24/7 (crypto) book — see "The WEEKEND rung"
  fri_flat_utc: 20
  weekend_release_utc: "22:10"   # your venue's first tradable Sunday minute
  news_currencies: "USD,EUR"

# notify:                        # optional — omit entirely to disable
#   telegram_token: ${TG_TOKEN}
#   telegram_chat: ${TG_CHAT}
```

`target.gateway_url`/`api_key`, `account.initial_balance`, and the whole `ladder:`/`notify:`/
`poll:`/`state:` sections are all optional except `target.name`, `target.gateway_url`,
`target.api_key`, and `account.initial_balance` — everything else falls back to the SOFT/HARD/
STATIC defaults shown above. A bad or missing field fails to start with a clear error; the
guardian never guesses at a threshold.

### Why no PyYAML?

`guardian/simpleyaml.py` is a deliberately restricted parser: two levels of `key:` nesting,
scalar values only, `#` comments, no lists/anchors/flow-style. That's the entire shape a
guardian config needs, and it means the runtime image has **zero pip dependencies** — every
dependency is a way for the brake to fail, and none is worth it for a config file this small.
If you need real YAML (lists, anchors, multi-doc), that's a signal this parser isn't the right
fit; swap in PyYAML at that point rather than extending the subset.

## Presets

Threshold sets sized *inside* each firm's rules — the guardian must trip before the firm does.
Copy one from `examples/` into `configs/<account-name>.yaml` and fill in `target`/`account`:

| preset | firm rule (daily/total) | SOFT / HARD / STATIC |
|---|---|---|
| `the5ers-high-stakes` | 5% / 10% static | 2.5 / 3.5 / 6 |
| `the5ers-hyper-growth` | 3% / 6% static | 1.5 / 2.2 / 4 |
| `ftmo` | 5% / 10% static | 2.5 / 3.5 / 6 |

## Development

```bash
python3 -m unittest discover -s tests -v   # 59 tests, no gateway or network needed
python3 -m ruff check guardian tests
python3 -m mypy
docker build -t qkt-guardrails:dev .
```

## Releasing and deploying

Deployments pin a **version tag**, never `latest`; the running guardian logs its version on
startup (`guardian[<name>] v0.2.0 up: ...`) and `python -m guardian --version` prints it. The
full procedure — version bump, tag, image, drills, roll-out — is in
[`docs/RELEASING.md`](docs/RELEASING.md); the change log is [`CHANGELOG.md`](CHANGELOG.md).

## Status

Acceptance-drilled 2026-08-31: live fill + kill/flatten round trip, SOFT/HARD/STATIC threshold
drills, restart recovery, news feed live. Restructured into a tested package with typed YAML
config in 2026-09. v0.2.0 (2026-09-04) is the first release deployed on the live prop account,
replacing the single-file guardian; battle scars land in `CHANGELOG.md` as they are paid for.
