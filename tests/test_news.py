import datetime as dt
import unittest

from guardian.news import high_impact_timestamps

FEED = [
    {"impact": "High", "country": "USD", "date": "2026-06-03T12:30:00-04:00"},
    {"impact": "High", "country": "GBP", "date": "2026-06-03T07:00:00-04:00"},
    {"impact": "Medium", "country": "USD", "date": "2026-06-03T10:00:00-04:00"},
    {"impact": "High", "country": "EUR", "date": "not-a-date"},
    "garbage",
]


class HighImpactFilterTest(unittest.TestCase):
    def test_default_currencies_keep_usd_and_eur_high_impact_only(self) -> None:
        got = high_impact_timestamps(FEED)
        want = dt.datetime.fromisoformat("2026-06-03T12:30:00-04:00").timestamp()
        self.assertEqual(got, [want])

    def test_configured_currencies_widen_the_window_set(self) -> None:
        got = high_impact_timestamps(FEED, ("USD", "GBP"))
        self.assertEqual(len(got), 2)
        self.assertEqual(got, sorted(got))

    def test_non_list_payload_yields_no_events(self) -> None:
        self.assertEqual(high_impact_timestamps({"error": "rate limited"}), [])


if __name__ == "__main__":
    unittest.main()
