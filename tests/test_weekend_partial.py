"""WEEKEND-PARTIAL: sparing 24/7 symbols must never soften an equity rung.

The weekend rung guards against gap risk in markets that shut, so naming crypto in
`ladder.weekend_exclude` leaves it trading. STATIC, DAILY-HARD, DAILY-SOFT and NEWS guard
equity instead, and every one of them must still take the account-global kill with nothing
spared -- that separation is the whole safety argument for this feature.
"""
from __future__ import annotations

import datetime as dt
import unittest

from guardian.config import LadderConfig
from guardian.ladder import evaluate
from guardian.state import GuardianState

FRIDAY_EVENING = dt.datetime(2026, 9, 4, 21, 30, tzinfo=dt.UTC)
SATURDAY = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.UTC)
FRIDAY_MORNING = dt.datetime(2026, 9, 4, 10, 0, tzinfo=dt.UTC)
INITIAL = 50000.0


def _state() -> GuardianState:
    return GuardianState(day="2026-09-04", prev_close=INITIAL, equity_now=INITIAL)


class WeekendPartialTest(unittest.TestCase):
    def test_without_exclusions_the_rung_is_unchanged(self) -> None:
        cfg = LadderConfig()
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, INITIAL, None)
        self.assertEqual(decision.reason, "WEEKEND")
        self.assertTrue(decision.want_kill)
        self.assertTrue(decision.want_flat)
        self.assertEqual(decision.spare_symbols, ())

    def test_exclusions_spare_symbols_and_leave_the_switch_off(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD,ETHUSD")
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, INITIAL, None)
        self.assertEqual(decision.reason, "WEEKEND-PARTIAL")
        self.assertFalse(decision.want_kill)
        self.assertTrue(decision.want_flat)
        self.assertEqual(decision.spare_symbols, ("BTCUSD", "ETHUSD"))

    def test_partial_flatten_re_runs_through_the_weekend(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD")
        state = _state()
        state, first = evaluate(state, cfg, INITIAL, FRIDAY_EVENING, INITIAL, None)
        _, later = evaluate(state, cfg, INITIAL, SATURDAY, INITIAL, None)
        self.assertTrue(first.want_flat)
        self.assertTrue(later.want_flat, "a weekday position appearing on Saturday must still be closed")
        self.assertFalse(later.want_kill)

    def test_symbols_are_upper_cased_and_trimmed(self) -> None:
        cfg = LadderConfig(weekend_exclude=" btcusd , ethusd ")
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, INITIAL, None)
        self.assertEqual(decision.spare_symbols, ("BTCUSD", "ETHUSD"))

    def test_outside_the_window_exclusions_do_nothing(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD")
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_MORNING, INITIAL, None)
        self.assertIsNone(decision.reason)
        self.assertFalse(decision.want_flat)
        self.assertEqual(decision.spare_symbols, ())

    def test_static_breach_in_the_window_still_kills_everything(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD")
        equity = INITIAL * (1 - cfg.static_pct / 100) - 1
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, equity, None)
        self.assertEqual(decision.reason, "STATIC")
        self.assertTrue(decision.want_kill)
        self.assertTrue(decision.want_flat)
        self.assertEqual(decision.spare_symbols, (), "an equity kill must spare nothing")

    def test_daily_hard_in_the_window_still_kills_everything(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD")
        equity = INITIAL * (1 - (cfg.hard_pct + 0.5) / 100)
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, equity, None)
        self.assertEqual(decision.reason, "DAILY-HARD")
        self.assertTrue(decision.want_kill)
        self.assertEqual(decision.spare_symbols, ())

    def test_daily_soft_in_the_window_still_kills(self) -> None:
        cfg = LadderConfig(weekend_exclude="BTCUSD")
        equity = INITIAL * (1 - (cfg.soft_pct + 0.2) / 100)
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, equity, None)
        self.assertEqual(decision.reason, "DAILY-SOFT")
        self.assertTrue(decision.want_kill)
        self.assertEqual(decision.spare_symbols, ())

    def test_friday_flat_off_ignores_exclusions_entirely(self) -> None:
        cfg = LadderConfig(friday_flat=False, weekend_exclude="BTCUSD")
        _, decision = evaluate(_state(), cfg, INITIAL, FRIDAY_EVENING, INITIAL, None)
        self.assertIsNone(decision.reason)
        self.assertFalse(decision.want_kill)
        self.assertFalse(decision.want_flat)


if __name__ == "__main__":
    unittest.main()
