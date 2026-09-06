import datetime as dt
import unittest

from guardian.config import LadderConfig
from guardian.ladder import Decision, day_anchor, evaluate, is_friday_flat_window, is_in_news_window
from guardian.state import GuardianState

UTC = dt.UTC


def at(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso).replace(tzinfo=UTC)


class DayAnchorTest(unittest.TestCase):
    def test_before_roll_hour_belongs_to_previous_day(self) -> None:
        self.assertEqual(day_anchor(at("2026-06-01T20:00:00"), roll_utc_hour=21), "2026-05-31")

    def test_at_or_after_roll_hour_belongs_to_current_day(self) -> None:
        self.assertEqual(day_anchor(at("2026-06-01T21:00:00"), roll_utc_hour=21), "2026-06-01")


class FridayWindowTest(unittest.TestCase):
    def test_friday_before_flat_hour_is_not_in_window(self) -> None:
        friday_morning = at("2026-06-05T10:00:00")  # a Friday
        self.assertFalse(is_friday_flat_window(friday_morning, fri_flat_utc=20))

    def test_friday_after_flat_hour_is_in_window(self) -> None:
        friday_evening = at("2026-06-05T21:00:00")
        self.assertTrue(is_friday_flat_window(friday_evening, fri_flat_utc=20))

    def test_all_saturday_is_in_window(self) -> None:
        self.assertTrue(is_friday_flat_window(at("2026-06-06T05:00:00"), fri_flat_utc=20))

    def test_sunday_before_release_time_is_in_window(self) -> None:
        self.assertTrue(is_friday_flat_window(at("2026-06-07T22:05:00"), fri_flat_utc=20))

    def test_sunday_after_release_time_is_not_in_window(self) -> None:
        self.assertFalse(is_friday_flat_window(at("2026-06-07T22:15:00"), fri_flat_utc=20))

    def test_monday_is_never_in_window(self) -> None:
        self.assertFalse(is_friday_flat_window(at("2026-06-08T23:00:00"), fri_flat_utc=20))

    def test_release_time_is_configurable_per_venue(self) -> None:
        sunday_2206 = at("2026-06-07T22:06:00")
        self.assertTrue(is_friday_flat_window(sunday_2206, fri_flat_utc=20))  # default 22:10
        self.assertFalse(is_friday_flat_window(sunday_2206, fri_flat_utc=20, release_utc=(22, 5)))
        late = (23, 30)
        self.assertTrue(is_friday_flat_window(at("2026-06-07T23:29:00"), fri_flat_utc=20, release_utc=late))
        self.assertFalse(is_friday_flat_window(at("2026-06-07T23:31:00"), fri_flat_utc=20, release_utc=late))

    def test_evaluate_honours_the_configured_release_time(self) -> None:
        cfg = LadderConfig(weekend_release_utc="22:05")
        state = GuardianState(day="2026-06-06", prev_close=10_000.0, equity_now=10_000.0)
        _, decision = evaluate(state, cfg, 10_000.0, at("2026-06-07T22:06:00"), 10_000.0, None)
        self.assertFalse(decision.want_kill)


class FridayFlatToggleTest(unittest.TestCase):
    def test_disabled_friday_flat_wants_no_kill_in_the_window(self) -> None:
        cfg = LadderConfig(friday_flat=False)
        state = GuardianState(day="2026-09-03", prev_close=50000.0, equity_now=50000.0)
        friday_evening = dt.datetime(2026, 9, 4, 21, 30, tzinfo=dt.UTC)
        state, decision = evaluate(state, cfg, 50000.0, friday_evening, 50000.0, None)
        self.assertFalse(decision.want_kill)

    def test_default_friday_flat_still_kills_in_the_window(self) -> None:
        cfg = LadderConfig()
        state = GuardianState(day="2026-09-03", prev_close=50000.0, equity_now=50000.0)
        friday_evening = dt.datetime(2026, 9, 4, 21, 30, tzinfo=dt.UTC)
        state, decision = evaluate(state, cfg, 50000.0, friday_evening, 50000.0, None)
        self.assertTrue(decision.want_kill)
        self.assertEqual(decision.reason, "WEEKEND")


class NewsWindowTest(unittest.TestCase):
    """The ladder sees (start, end) intervals; the source decides their shape."""

    def test_inside_a_window_is_in_window(self) -> None:
        now = at("2026-06-01T12:00:00").timestamp()
        self.assertTrue(is_in_news_window(at("2026-06-01T12:00:00"), [(now - 120, now + 180)]))

    def test_window_edges_are_inclusive(self) -> None:
        now = at("2026-06-01T12:00:00").timestamp()
        self.assertTrue(is_in_news_window(at("2026-06-01T12:00:00"), [(now - 300, now)]))
        self.assertTrue(is_in_news_window(at("2026-06-01T12:00:00"), [(now, now + 300)]))

    def test_outside_every_window_is_not_in_window(self) -> None:
        now = at("2026-06-01T12:00:00").timestamp()
        later, earlier = (now + 600, now + 1200), (now - 1200, now - 600)
        self.assertFalse(is_in_news_window(at("2026-06-01T12:00:00"), [later, earlier]))

    def test_a_session_long_window_covers_the_whole_session(self) -> None:
        """A bank holiday is one window from 00:00 to 24:00, not a five-minute point."""
        day = at("2026-06-01T00:00:00").timestamp()
        for hour in (0, 9, 15, 23):
            self.assertTrue(is_in_news_window(at(f"2026-06-01T{hour:02d}:30:00"), [(day, day + 86_400)]))
        self.assertFalse(is_in_news_window(at("2026-06-02T00:30:00"), [(day, day + 86_400)]))

    def test_no_windows_is_not_in_window(self) -> None:
        self.assertFalse(is_in_news_window(at("2026-06-01T12:00:00"), None))
        self.assertFalse(is_in_news_window(at("2026-06-01T12:00:00"), ()))


class EvaluateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = LadderConfig(soft_pct=2.5, hard_pct=3.5, static_pct=6.0, roll_utc_hour=21, fri_flat_utc=20)

    def test_flat_equity_with_no_drawdown_wants_no_kill(self) -> None:
        state = GuardianState(day="2026-06-01", prev_close=10_000.0)
        _, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-01T22:00:00"), 10_000.0, None)
        self.assertEqual(decision, Decision(want_kill=False, want_flat=False, reason=None, day_dd_pct=0.0))

    def test_soft_drawdown_kills_without_flattening(self) -> None:
        state = GuardianState(day="2026-06-01", prev_close=10_000.0)
        _, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-01T22:00:00"), 9_720.0, None)  # -2.8%
        self.assertTrue(decision.want_kill)
        self.assertFalse(decision.want_flat)
        self.assertEqual(decision.reason, "DAILY-SOFT")

    def test_hard_drawdown_kills_and_flattens_once(self) -> None:
        state = GuardianState(day="2026-06-01", prev_close=10_000.0)
        new_state, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-01T22:00:00"), 9_600.0, None)  # -4%
        self.assertTrue(decision.want_kill)
        self.assertTrue(decision.want_flat)
        self.assertEqual(decision.reason, "DAILY-HARD")
        self.assertTrue(new_state.daily_lock)

        # a second cycle at the same drawdown must not re-flatten
        _, decision2 = evaluate(new_state, self.cfg, 10_000.0, at("2026-06-01T22:05:00"), 9_600.0, None)
        self.assertTrue(decision2.want_kill)
        self.assertFalse(decision2.want_flat)
        self.assertEqual(decision2.reason, "DAILY-HARD")

    def test_daily_hard_lock_clears_on_next_day_rollover(self) -> None:
        state = GuardianState(day="2026-06-01", prev_close=10_000.0, daily_lock=True, lock="daily", equity_now=9_600.0)
        new_state, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-02T21:00:00"), 9_900.0, None)
        self.assertFalse(decision.want_kill)
        self.assertFalse(new_state.daily_lock)
        self.assertIsNone(new_state.lock)

    def test_static_floor_locks_and_survives_day_rollover(self) -> None:
        state = GuardianState(day="2026-06-01", prev_close=10_000.0)
        new_state, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-01T22:00:00"), 9_300.0, None)  # -7%
        self.assertEqual(decision.reason, "STATIC")
        self.assertTrue(decision.want_flat)
        self.assertEqual(new_state.lock, "static")

        # equity recovers, but the static lock is NOT auto-released across a day roll
        _, decision2 = evaluate(new_state, self.cfg, 10_000.0, at("2026-06-02T21:00:00"), 9_900.0, None)
        self.assertEqual(decision2.reason, "STATIC-HOLD")
        self.assertFalse(decision2.want_flat)

    def test_weekend_window_kills_and_flattens_once_on_friday(self) -> None:
        state = GuardianState(day="2026-06-05", prev_close=10_000.0)
        new_state, decision = evaluate(state, self.cfg, 10_000.0, at("2026-06-05T21:00:00"), 10_000.0, None)
        self.assertEqual(decision.reason, "WEEKEND")
        self.assertTrue(decision.want_flat)

        _, decision2 = evaluate(new_state, self.cfg, 10_000.0, at("2026-06-05T21:05:00"), 10_000.0, None)
        self.assertEqual(decision2.reason, "WEEKEND")
        self.assertFalse(decision2.want_flat)

    def test_news_window_kills_without_flattening(self) -> None:
        now = at("2026-06-03T12:00:00")  # a Wednesday, clear of the weekend window
        state = GuardianState(day="2026-06-03", prev_close=10_000.0)
        t = now.timestamp()
        _, decision = evaluate(state, self.cfg, 10_000.0, now, 10_000.0, [(t - 300, t + 300)])
        self.assertEqual(decision.reason, "NEWS")
        self.assertFalse(decision.want_flat)

    def test_static_takes_priority_over_every_other_rung(self) -> None:
        now = at("2026-06-05T21:00:00")  # Friday evening: would also trigger WEEKEND
        state = GuardianState(day="2026-06-05", prev_close=10_000.0)
        t = now.timestamp()
        _, decision = evaluate(state, self.cfg, 10_000.0, now, 9_300.0, [(t - 300, t + 300)])
        self.assertEqual(decision.reason, "STATIC")


if __name__ == "__main__":
    unittest.main()
