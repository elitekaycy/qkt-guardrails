"""The risk ladder: pure decision logic, no I/O.

Every function here takes its inputs as arguments and returns a value — no
gateway calls, no clock reads beyond the `now` passed in, no state mutation
in place. That's what makes `tests/test_ladder.py` able to hit every rung
(SOFT, HARD, STATIC, NEWS, FRIDAY, and the transitions between them) without
a running gateway or real wall-clock time.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from guardian.config import LadderConfig
from guardian.state import GuardianState


@dataclass(frozen=True)
class Decision:
    want_kill: bool
    want_flat: bool
    reason: str | None
    day_dd_pct: float


def day_anchor(now: dt.datetime, roll_utc_hour: int) -> str:
    """The firm's trading day: rolls over at `roll_utc_hour` UTC."""
    d = now.date()
    if now.hour < roll_utc_hour:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def is_friday_flat_window(now: dt.datetime, fri_flat_utc: int) -> bool:
    """From Friday `fri_flat_utc`:00 UTC through Sunday 22:10 UTC."""
    if now.weekday() == 4:
        return now.hour >= fri_flat_utc
    if now.weekday() == 5:
        return True
    if now.weekday() == 6:
        return now.hour < 22 or (now.hour == 22 and now.minute < 10)
    return False


def is_in_news_window(now: dt.datetime, news_event_timestamps: list[float] | None, pad_minutes: int) -> bool:
    if not news_event_timestamps:
        return False
    now_ts = now.timestamp()
    pad = pad_minutes * 60
    return any(abs(now_ts - ts) <= pad for ts in news_event_timestamps)


def roll_day(state: GuardianState, now: dt.datetime, cfg: LadderConfig, equity: float) -> GuardianState:
    """Returns `state` unchanged, or a new state with the day's anchor rolled forward."""
    anchor = day_anchor(now, cfg.roll_utc_hour)
    if state.day == anchor:
        return state
    prev = state.equity_now if state.equity_now is not None else equity
    lock = None if state.lock == "daily" else state.lock
    return GuardianState(
        day=anchor,
        prev_close=prev,
        equity_now=state.equity_now,
        daily_lock=False,
        lock=lock,
        fri_flat=state.fri_flat,
        guard_kill=state.guard_kill,
    )


def evaluate(
    state: GuardianState,
    cfg: LadderConfig,
    initial_balance: float,
    now: dt.datetime,
    equity: float,
    news_event_timestamps: list[float] | None,
) -> tuple[GuardianState, Decision]:
    """Runs one evaluation cycle: rolls the day if needed, then walks the ladder
    top-down (STATIC > DAILY-HARD > DAILY-SOFT > WEEKEND > NEWS) and returns the
    resulting state plus what the caller should do about the kill switch."""
    state = roll_day(state, now, cfg, equity)
    state.equity_now = equity

    prev_close = state.prev_close if state.prev_close is not None else equity
    day_dd_pct = (prev_close - equity) / prev_close * 100 if prev_close > 0 else 0.0
    static_floor = initial_balance * (1 - cfg.static_pct / 100)

    want_kill = False
    want_flat = False
    reason: str | None = None

    if equity <= static_floor:
        want_kill, want_flat, reason = True, True, "STATIC"
        state.lock = "static"
    elif state.lock == "static":
        want_kill, reason = True, "STATIC-HOLD"
    elif day_dd_pct >= cfg.hard_pct or state.daily_lock:
        want_kill, reason = True, "DAILY-HARD"
        if not state.daily_lock:
            want_flat = True
        state.daily_lock = True
        state.lock = "daily"
    elif day_dd_pct >= cfg.soft_pct:
        want_kill, reason = True, "DAILY-SOFT"
    elif is_friday_flat_window(now, cfg.fri_flat_utc):
        want_kill, reason = True, "WEEKEND"
        anchor = day_anchor(now, cfg.roll_utc_hour)
        if now.weekday() == 4 and state.fri_flat != anchor:
            want_flat = True
            state.fri_flat = anchor
    elif is_in_news_window(now, news_event_timestamps, cfg.news_pad_min):
        want_kill, reason = True, "NEWS"

    return state, Decision(want_kill=want_kill, want_flat=want_flat, reason=reason, day_dd_pct=day_dd_pct)
