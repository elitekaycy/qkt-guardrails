"""Wires config + gateway + ladder + state into the run loop."""
from __future__ import annotations

import datetime as dt
import time

from guardian import __version__
from guardian.config import GuardianConfig
from guardian.gateway import GatewayClient, GatewayError
from guardian.hubjournal import HubJournalSource
from guardian.ladder import evaluate
from guardian.logging import log
from guardian.news import ForexFactorySource, NewsCache, Source
from guardian.notify import TelegramNotifier
from guardian.state import GuardianState

# Default for `poll.blind_after_failures`; the config decides, this is the fallback.
BLIND_AFTER_FAILURES = 3


class Sight:
    """Consecutive failed polls. A guardian that cannot read equity is not guarding,
    and nothing else in the stack can tell: it alerts once when it goes blind and
    once when it sees again, never on the single hiccups in between."""

    def __init__(self, blind_after: int = BLIND_AFTER_FAILURES) -> None:
        self._blind_after = blind_after
        self.failures = 0

    @property
    def blind(self) -> bool:
        return self.failures >= self._blind_after

    def failed(self, error: BaseException) -> str | None:
        self.failures += 1
        if self.failures != self._blind_after:
            return None
        return f"BLIND: {self.failures} polls failed, equity is not being watched. Last: {error}"

    def succeeded(self) -> str | None:
        was_blind = self.blind
        failures = self.failures
        self.failures = 0
        if not was_blind:
            return None
        return f"sight restored after {failures} failed polls"


def build_news_cache(cfg: GuardianConfig) -> NewsCache:
    """The event-window providers for this account.

    One source today, chosen by config: the ForexFactory feed over HTTP, or a qkt-data-hub
    journal on disk. The hub path is preferred where one is running, because it removes the
    brake's only outbound network call -- the observed failure of that feed was an HTML error
    page served with a 200, which parses to zero events and empties the windows while the
    system still looks healthy. A second provider is another entry in this list.
    """
    sources: list[Source] = []
    if cfg.ladder.news_hub_root:
        log(f"news: reading windows from the hub store at {cfg.ladder.news_hub_root} (no feed fetch)")
        sources.append(
            HubJournalSource(
                cfg.ladder.news_hub_root,
                cfg.ladder.news_currency_codes,
                include_holidays=cfg.ladder.news_include_holidays,
                pad_seconds=cfg.ladder.news_pad_min * 60,
                stale_after_seconds=cfg.ladder.news_hub_stale_after_seconds,
            )
        )
    else:
        sources.append(
            ForexFactorySource(
                cfg.ladder.news_feed,
                cfg.ladder.news_currency_codes,
                include_holidays=cfg.ladder.news_include_holidays,
                pad_seconds=cfg.ladder.news_pad_min * 60,
            )
        )
    return NewsCache(
        sources,
        timeout_seconds=cfg.ladder.news_timeout_seconds,
        refresh_steady_seconds=cfg.ladder.news_refresh_steady_seconds,
        retry_seconds=cfg.ladder.news_retry_seconds,
    )


def run_forever(cfg: GuardianConfig) -> None:
    gateway = GatewayClient(cfg.target.gateway_url, cfg.target.api_key, cfg.poll.gateway_timeout)
    notifier = TelegramNotifier(cfg.notify, cfg.notify.telegram_timeout_seconds)
    news = build_news_cache(cfg)
    state = GuardianState.load(cfg.state_path)
    sight = Sight(cfg.poll.blind_after_failures)

    weekend = (
        f"weekend=Fri{cfg.ladder.fri_flat_utc:02d}:00->Sun{cfg.ladder.weekend_release_utc}UTC"
        if cfg.ladder.friday_flat
        else "weekend=off"
    )
    holidays = "+holidays" if cfg.ladder.news_include_holidays else ""
    log(
        f"guardian[{cfg.target.name}] v{__version__} up: initial={cfg.account.initial_balance} "
        f"soft={cfg.ladder.soft_pct}% hard={cfg.ladder.hard_pct}% static={cfg.ladder.static_pct}% "
        f"roll={cfg.ladder.roll_utc_hour}UTC pad={cfg.ladder.news_pad_min}m "
        f"news={','.join(cfg.ladder.news_currency_codes)}{holidays} {weekend} "
        f"poll={cfg.poll.interval_seconds}s timeout={cfg.poll.gateway_timeout:g}s "
        f"blind_after={cfg.poll.blind_after_failures}"
    )
    # Wait one fetch timeout, at most, for the sources to arm so the NEWS rung is live from
    # poll one; every refresh runs on the news thread, never on this loop.
    news.start()
    if not news.armed:
        log(f"[{cfg.target.name}] news source(s) not armed at startup: {', '.join(news.unarmed)}; "
            "NEWS rung covers nothing from them until they load")

    while True:
        alert: str | None = None
        try:
            state = run_once(cfg, gateway, notifier, news, state)
            alert = sight.succeeded()
        except GatewayError as e:
            log("gateway error:", e)
            alert = sight.failed(e)
        except Exception as e:  # noqa: BLE001 — a guard loop must never die
            log("loop error:", e)
            alert = sight.failed(e)
        if alert:
            log(f"[{cfg.target.name}]", alert)
            notifier.send(f"{cfg.target.name}: {alert}")
        time.sleep(cfg.poll.interval_seconds)


def run_once(
    cfg: GuardianConfig,
    gateway: GatewayClient,
    notifier: TelegramNotifier,
    news: NewsCache,
    state: GuardianState,
    now: dt.datetime | None = None,
) -> GuardianState:
    now = now if now is not None else dt.datetime.now(dt.UTC)
    account = gateway.account()
    raw_equity = account.get("equity")
    # A payload without a positive numeric equity is DATA, not a drawdown: 0.0
    # would read as "below the static floor" and flatten the whole book on a
    # telemetry glitch. On valid data the STATIC rung engages long before
    # equity could approach zero, so nothing real is lost by refusing here.
    try:
        equity = float(raw_equity)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise GatewayError(f"account payload without numeric equity: {raw_equity!r}") from None
    if equity <= 0:
        raise GatewayError(f"account payload with non-positive equity: {equity!r}")

    state, decision = evaluate(state, cfg.ladder, cfg.account.initial_balance, now, equity, news.windows())

    kill_switch_active = gateway.kill_switch_active()

    if decision.want_kill and not kill_switch_active:
        gateway.kill(decision.want_flat)
        state.guard_kill = True
        msg = (
            f"KILL engaged ({decision.reason}) equity={equity:.2f} "
            f"dayDD={decision.day_dd_pct:.2f}% flatten={decision.want_flat}"
        )
        log(f"[{cfg.target.name}]", msg)
        notifier.send(f"{cfg.target.name}: {msg}")
    elif decision.want_kill and decision.want_flat:
        gateway.kill(flatten=True)
        state.guard_kill = True
        log(f"[{cfg.target.name}] flatten re-issued ({decision.reason})")
    elif not decision.want_kill and kill_switch_active:
        # Only release a switch the guardian itself engaged — a manual
        # operator kill stays engaged until the operator releases it.
        if state.guard_kill:
            gateway.release()
            state.guard_kill = False
            log(f"[{cfg.target.name}] kill released equity={equity:.2f} dayDD={decision.day_dd_pct:.2f}%")
            notifier.send(f"{cfg.target.name}: kill released, equity={equity:.2f}")
    elif not decision.want_kill and not kill_switch_active:
        state.guard_kill = False

    state.save(cfg.state_path)
    return state
