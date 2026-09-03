"""Wires config + gateway + ladder + state into the run loop."""
from __future__ import annotations

import datetime as dt
import time

from guardian.config import GuardianConfig
from guardian.gateway import GatewayClient, GatewayError
from guardian.ladder import evaluate
from guardian.logging import log
from guardian.news import NewsCache
from guardian.notify import TelegramNotifier
from guardian.state import GuardianState

# Three straight failed polls, the same window the container healthcheck calls stale.
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


def run_forever(cfg: GuardianConfig) -> None:
    gateway = GatewayClient(cfg.target.gateway_url, cfg.target.api_key)
    notifier = TelegramNotifier(cfg.notify)
    news = NewsCache(cfg.ladder.news_feed)
    state = GuardianState.load(cfg.state_path)
    sight = Sight()

    log(
        f"guardian[{cfg.target.name}] up: initial={cfg.account.initial_balance} "
        f"soft={cfg.ladder.soft_pct}% hard={cfg.ladder.hard_pct}% static={cfg.ladder.static_pct}% "
        f"roll={cfg.ladder.roll_utc_hour}UTC pad={cfg.ladder.news_pad_min}m"
    )

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
) -> GuardianState:
    now = dt.datetime.now(dt.UTC)
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

    state, decision = evaluate(state, cfg.ladder, cfg.account.initial_balance, now, equity, news.events())

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
