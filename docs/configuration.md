# Configuration

One YAML file per account (`configs/<account-name>.yaml`, gitignored: never commit real
values). `${VAR}` in any string is substituted from the environment at load time, so secrets
stay in `.env`. Non-secret fields (`target.name`, `gateway_url`, `initial_balance`) are literal.

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
  roll_utc_hour: 21              # the firm's day roll, UTC hour; or, for a server day that
  # roll_tz: America/New_York    # follows daylight saving, a wall-clock hour in a timezone
  # roll_local_hour: 17          # (set both, and leave roll_utc_hour out)
  friday_flat: true              # false for a 24/7 (crypto) book, see ladder.md
  fri_flat_utc: 20
  weekend_release_utc: "22:10"   # your venue's first tradable Sunday minute
  news_currencies: "USD,EUR"
  # news_include_holidays: false # a bank holiday for these currencies is a session-long window
  # news_timeout_seconds: 30     # fetch runs on the news thread, never the guard loop
  # news_refresh_steady_seconds: 21600
  # news_retry_seconds: 300      # after a FAILED fetch; last-known windows stay in force

# notify:                        # optional: omit entirely to disable
#   telegram_token: ${TG_TOKEN}
#   telegram_chat: ${TG_CHAT}
#   telegram_timeout_seconds: 10

# poll:
#   interval_seconds: 30
#   gateway_timeout_seconds: 20  # default min(20, interval_seconds); may not exceed the interval
#   blind_after_failures: 3

# health:
#   stale_cycles: 3              # container unhealthy after this many intervals without a saved cycle
```

Every commented value is the default, i.e. exactly what the guardian ran with before the knob
existed. Unknown keys are rejected at load so a typo (`soft_pcnt`) cannot silently leave a
default in place. Only `target.name`, `target.gateway_url`, `target.api_key` and
`account.initial_balance` are required; the ladder falls back to the SOFT/HARD/STATIC defaults
above. A bad or missing field fails to start with a clear error: the guardian never guesses at
a threshold.

## One process per account

A guardian never watches more than one account: a hang or bug in one account's poll loop must
never delay the kill decision for another. Run one container per account, each reading one
config that names the gateway it watches. State lives in the file named by `state.path`
(default `/state/guardian.json`), written atomically, so a restart never loses the day's
rollover anchor, the static lock, or which kill switch the guardian owns. Edit state only
while the guardian is stopped.

## Docker

One small `python:3.12-slim` image, non-root user (uid 10001: `chown -R 10001:10001` a
bind-mounted state dir). The `HEALTHCHECK` checks state-file freshness, not just that the
process runs. Images are pushed to GHCR on every tag. See `docker-compose.example.yml`.

## Why no PyYAML?

`guardian/simpleyaml.py` is a deliberately restricted parser: two levels of `key:` nesting,
scalar values only, `#` comments, no lists, anchors or flow style. That is the entire shape a
guardian config needs, and it means the runtime image has **zero pip dependencies**. Every
dependency is a way for the brake to fail. If you need real YAML, swap in PyYAML at that point
rather than extending the subset.

## News sources

`guardian/news.py` separates three things so a new provider touches only the first:

```
Source.fetch(timeout) -> list[Event] | None     one provider, one transformer
Event(start, end, scope, severity, source)      the fields that influence the decision
windows(events) -> ((start, end), ...)          what the ladder consumes
```

An `Event` carries its own UTC window: ForexFactory pads a release by `news_pad_min` and makes
a bank holiday the whole calendar day; an earnings source would use the call's duration. The
ladder only asks "is now inside any window". `NewsCache` refreshes every source on a daemon
thread with per-source backoff, merges their windows, and keeps a source's last-known windows
through its outages. `start()` waits at most one fetch timeout for the sources to arm.

To read windows from a qkt-data-hub store on disk instead of the feed, set
`ladder.news_hub_root`. To add a provider, implement `name` and `fetch` (return `None` on
failure, never raise on bad data), give each event an honest window, and append it in
`build_news_cache`. Config for a second source is not built yet: `simpleyaml` has no lists.
