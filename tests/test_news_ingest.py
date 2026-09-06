"""The ForexFactory feed as it actually is, pinned row-for-row, and the source/cache seam.

FEED below is a verbatim sample from `ff_calendar_thisweek.json` on 2026-09-06 (titles
kept, values trimmed), so the transformer is tested against the real schema: `country` is
a currency code, `date` carries a New York UTC offset, `impact` is one of exactly four words.
"""
import datetime as dt
import threading
import unittest

from guardian.news import Event, NewsCache, event_timestamps, forexfactory_events, high_impact_timestamps, windows

FEED = [
    {"title": "ANZ Job Advertisements m/m", "country": "AUD", "date": "2026-09-06T21:30:00-04:00",
     "impact": "Low", "forecast": "", "previous": "0.8%"},
    {"title": "Bank Holiday", "country": "USD", "date": "2026-09-07T00:00:00-04:00",
     "impact": "Holiday", "forecast": "", "previous": ""},
    {"title": "Bank Holiday", "country": "CAD", "date": "2026-09-07T00:00:00-04:00",
     "impact": "Holiday", "forecast": "", "previous": ""},
    {"title": "BRICS Summit", "country": "All", "date": "2026-09-08T00:00:00-04:00",
     "impact": "Low", "forecast": "", "previous": ""},
    {"title": "Main Refinancing Rate", "country": "EUR", "date": "2026-09-10T08:15:00-04:00",
     "impact": "High", "forecast": "2.15%", "previous": "2.15%"},
    {"title": "Monetary Policy Statement", "country": "EUR", "date": "2026-09-10T08:15:00-04:00",
     "impact": "High", "forecast": "", "previous": ""},
    {"title": "Core PPI m/m", "country": "USD", "date": "2026-09-10T08:30:00-04:00",
     "impact": "High", "forecast": "0.3%", "previous": "0.9%"},
    {"title": "PPI m/m", "country": "USD", "date": "2026-09-10T08:30:00-04:00",
     "impact": "High", "forecast": "0.3%", "previous": "0.9%"},
    {"title": "ECB Press Conference", "country": "EUR", "date": "2026-09-10T08:45:00-04:00",
     "impact": "High", "forecast": "", "previous": ""},
    {"title": "Core CPI m/m", "country": "USD", "date": "2026-09-11T08:30:00-04:00",
     "impact": "High", "forecast": "0.3%", "previous": "0.3%"},
    {"title": "CPI m/m", "country": "USD", "date": "2026-09-11T08:30:00-04:00",
     "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
    {"title": "Unemployment Claims", "country": "USD", "date": "2026-09-10T08:30:00-04:00",
     "impact": "Medium", "forecast": "236K", "previous": "237K"},
    {"title": "BOJ Gov Speaks", "country": "JPY", "date": "2026-09-09T22:00:00-04:00",
     "impact": "High", "forecast": "", "previous": ""},
]

PAD = 300.0


def _utc(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp()


def _win(iso: str) -> tuple[float, float]:
    t = _utc(iso)
    return (t - PAD, t + PAD)


class RealSchemaTest(unittest.TestCase):
    def test_new_york_offset_is_converted_to_utc(self) -> None:
        """08:15 EDT is 12:15 UTC. Getting this wrong shifts every window by four hours."""
        (ev, *_) = forexfactory_events(FEED, ("EUR",), pad_seconds=0)
        when = dt.datetime.fromtimestamp(ev.start, dt.UTC)
        self.assertEqual((when.hour, when.minute), (12, 15))

    def test_same_minute_releases_collapse_to_one_window(self) -> None:
        """Four USD CPI/PPI rows and two ECB rows at the same minutes are one window each."""
        got = windows(forexfactory_events(FEED, ("USD", "EUR"), pad_seconds=PAD))
        self.assertEqual(
            got,
            (_win("2026-09-10T08:15:00-04:00"), _win("2026-09-10T08:30:00-04:00"),
             _win("2026-09-10T08:45:00-04:00"), _win("2026-09-11T08:30:00-04:00")),
        )

    def test_a_release_is_padded_on_both_sides(self) -> None:
        (ev,) = forexfactory_events(FEED, ("EUR",), pad_seconds=120)[:1]
        centre = _utc("2026-09-10T08:15:00-04:00")
        self.assertEqual((ev.start, ev.end), (centre - 120, centre + 120))

    def test_only_high_impact_opens_a_window_by_default(self) -> None:
        got = forexfactory_events(FEED, ("USD",))
        self.assertTrue(all(e.severity == "high" for e in got))
        self.assertTrue(any(e.title == "PPI m/m" for e in got))
        self.assertFalse(any(e.title == "Unemployment Claims" for e in got))   # Medium, same minute
        self.assertFalse(any(e.title == "Bank Holiday" for e in got))

    def test_a_holiday_is_a_whole_session_not_a_point(self) -> None:
        """The row is stamped 00:00 New York with no duration; the hazard lasts the day."""
        (hol,) = [e for e in forexfactory_events(FEED, ("USD",), include_holidays=True) if e.severity == "holiday"]
        self.assertEqual(hol.start, _utc("2026-09-07T00:00:00-04:00"))
        self.assertEqual(hol.end - hol.start, 86_400)
        self.assertEqual(hol.scope, "USD")
        self.assertEqual(hol.source, "forexfactory")

    def test_holidays_are_scoped_to_the_configured_currency(self) -> None:
        got = forexfactory_events(FEED, ("USD",), include_holidays=True)
        self.assertEqual(sum(1 for e in got if e.severity == "holiday"), 1)   # USD yes, CAD no

    def test_country_is_a_currency_code_matched_case_insensitively(self) -> None:
        self.assertEqual(forexfactory_events(FEED, ("usd",)), forexfactory_events(FEED, ("USD",)))
        self.assertEqual(forexfactory_events(FEED, (" eur ",)), forexfactory_events(FEED, ("EUR",)))

    def test_the_all_pseudo_currency_is_selectable(self) -> None:
        self.assertEqual(forexfactory_events(FEED, ("All",)), [])   # BRICS is Low impact
        feed = FEED + [{"country": "All", "impact": "High", "date": "2026-09-08T09:00:00-04:00"}]
        got = windows(forexfactory_events(feed, ("ALL",), pad_seconds=PAD))
        self.assertEqual(got, (_win("2026-09-08T09:00:00-04:00"),))

    def test_unrelated_currencies_never_leak_in(self) -> None:
        self.assertFalse(any(e.scope == "JPY" for e in forexfactory_events(FEED, ("USD", "EUR"))))

    def test_centre_helpers_keep_working(self) -> None:
        self.assertEqual(high_impact_timestamps(FEED), event_timestamps(FEED, ("USD", "EUR")))
        self.assertEqual(event_timestamps(FEED, ("EUR",))[0], _utc("2026-09-10T08:15:00-04:00"))


class MalformedInputTest(unittest.TestCase):
    def test_naive_date_is_rejected_not_misread_as_local_time(self) -> None:
        feed = [{"country": "USD", "impact": "High", "date": "2026-09-10T08:30:00"}]
        self.assertEqual(forexfactory_events(feed, ("USD",)), [])

    def test_z_suffix_is_accepted_as_utc(self) -> None:
        feed = [{"country": "USD", "impact": "High", "date": "2026-09-10T12:30:00Z"}]
        (ev,) = forexfactory_events(feed, ("USD",), pad_seconds=0)
        self.assertEqual(ev.start, _utc("2026-09-10T12:30:00+00:00"))

    def test_bad_rows_are_skipped_one_at_a_time(self) -> None:
        feed = [
            "garbage", None, 42,
            {"country": "USD", "impact": "High"},                              # no date
            {"country": "USD", "impact": "High", "date": None},
            {"country": "USD", "impact": "High", "date": "tomorrow"},
            {"country": "USD", "impact": "Severe", "date": "2026-09-10T08:30:00-04:00"},  # unknown impact
            {"country": "USD", "impact": "High", "date": "2026-09-10T08:30:00-04:00"},    # the good one
        ]
        got = windows(forexfactory_events(feed, ("USD",), pad_seconds=PAD))
        self.assertEqual(got, (_win("2026-09-10T08:30:00-04:00"),))

    def test_non_list_payloads_yield_nothing(self) -> None:
        for payload in ({"error": "rate limited"}, "[]", None, 7):
            self.assertEqual(forexfactory_events(payload, ("USD",)), [])

    def test_an_event_cannot_end_before_it_starts(self) -> None:
        with self.assertRaises(ValueError):
            Event(10.0, 5.0, "USD", "high", "test")


class _FakeSource:
    """Scripted results: each fetch pops the next item; None means failure."""

    def __init__(self, name: str, results: list) -> None:
        self.name = name
        self._results = results
        self.calls = 0

    def fetch(self, timeout_seconds: float) -> list[Event] | None:
        self.calls += 1
        return self._results.pop(0) if self._results else None


def _ev(start: float, end: float | None = None, source: str = "a") -> Event:
    return Event(start, start + 60 if end is None else end, "USD", "high", source)


class CacheTest(unittest.TestCase):
    """Deterministic clock and sources; no network, no sleeping."""

    def _cache(self, *sources: _FakeSource) -> tuple[NewsCache, list[float]]:
        now = [1_000_000.0]
        cache = NewsCache(sources, clock=lambda: now[0], refresh_steady_seconds=6 * 3600, retry_seconds=300)
        return cache, now

    def test_windows_never_fetches(self) -> None:
        src = _FakeSource("a", [[_ev(1)]])
        cache, _ = self._cache(src)
        self.assertEqual(cache.windows(), ())
        self.assertFalse(cache.armed)
        self.assertEqual(cache.unarmed, ("a",))
        self.assertEqual(src.calls, 0)

    def test_success_schedules_the_steady_interval(self) -> None:
        src = _FakeSource("a", [[_ev(1)], [_ev(2)]])
        cache, now = self._cache(src)
        self.assertTrue(cache.refresh())
        self.assertEqual(cache.windows(), ((1.0, 61.0),))
        now[0] += 6 * 3600 - 1
        self.assertFalse(cache.refresh())          # not due yet
        now[0] += 1
        self.assertTrue(cache.refresh())
        self.assertEqual(cache.windows(), ((2.0, 62.0),))
        self.assertEqual(src.calls, 2)

    def test_failure_keeps_last_known_and_retries_sooner(self) -> None:
        """The startup-outage case: a failed fetch must not wait a full interval."""
        src = _FakeSource("a", [[_ev(1)], None, [_ev(3)]])
        cache, now = self._cache(src)
        cache.refresh()
        now[0] += 6 * 3600
        self.assertFalse(cache.refresh())          # attempted, failed
        self.assertEqual(cache.windows(), ((1.0, 61.0),))   # last-known kept
        now[0] += 300 - 1
        self.assertFalse(cache.refresh())          # retry not yet due
        now[0] += 1
        self.assertTrue(cache.refresh())
        self.assertEqual(cache.windows(), ((3.0, 63.0),))

    def test_first_failure_retries_on_retry_cadence_not_an_hour(self) -> None:
        src = _FakeSource("a", [None, [_ev(1)]])
        cache, now = self._cache(src)
        self.assertFalse(cache.refresh())
        self.assertFalse(cache.armed)
        now[0] += 300
        self.assertTrue(cache.refresh())
        self.assertTrue(cache.armed)

    def test_an_empty_week_still_arms_the_source(self) -> None:
        cache, _ = self._cache(_FakeSource("a", [[]]))
        cache.refresh()
        self.assertTrue(cache.armed)
        self.assertEqual(cache.windows(), ())

    def test_sources_fail_independently_and_windows_merge(self) -> None:
        """One dead provider must not blank the other: the seam scaling is built on."""
        a = _FakeSource("calendar", [[_ev(10, source="calendar")], None])
        b = _FakeSource("earnings", [None, [_ev(500, 900, source="earnings")]])
        cache, now = self._cache(a, b)
        cache.refresh()
        self.assertEqual(cache.unarmed, ("earnings",))
        self.assertEqual(cache.windows(), ((10.0, 70.0),))
        now[0] += 300
        cache.refresh()                            # earnings retries; calendar is not due yet
        self.assertTrue(cache.armed)
        self.assertEqual(cache.windows(), ((10.0, 70.0), (500.0, 900.0)))
        self.assertEqual((a.calls, b.calls), (1, 2))
        now[0] += 6 * 3600
        cache.refresh()                            # calendar fails now; its windows survive
        self.assertEqual(cache.windows(), ((10.0, 70.0), (500.0, 900.0)))

    def test_start_arms_within_the_budget_then_hands_off_to_a_thread(self) -> None:
        src = _FakeSource("a", [[_ev(1)]])
        cache = NewsCache([src], timeout_seconds=2)
        cache.start()
        self.addCleanup(cache.stop)
        self.assertEqual(cache.windows(), ((1.0, 61.0),))   # armed before start() returned
        self.assertIsNotNone(cache._thread)
        self.assertTrue(cache._thread.daemon)
        cache.start()                                        # idempotent
        self.assertEqual(src.calls, 1)

    def test_start_returns_after_the_budget_even_if_a_source_hangs(self) -> None:
        """Bounded regardless of source count: a slow provider cannot hold up the guard."""
        release = threading.Event()

        class Hung:
            name = "hung"

            def fetch(self, timeout_seconds: float) -> list[Event] | None:
                release.wait(5)
                return [_ev(9)]

        cache = NewsCache([Hung()], timeout_seconds=0.2)
        started = threading.Event()

        def run() -> None:
            cache.start()
            started.set()

        threading.Thread(target=run, daemon=True).start()
        self.assertTrue(started.wait(2))           # start() came back within the budget
        self.assertEqual(cache.windows(), ())      # answered immediately, mid-fetch
        self.assertFalse(cache.armed)
        release.set()
        cache.stop()


if __name__ == "__main__":
    unittest.main()
