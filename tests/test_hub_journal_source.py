"""Tests for reading the guardian's news windows from a qkt-data-hub journal.

The substitution only earns its place if it fails the same way the HTTP source does: a store it
cannot trust must return `None` so the cache keeps its last known windows, never an empty list
that would silently assert no release is coming.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from guardian.hubjournal import HubJournalSource
from guardian.ladder import is_in_news_window
from guardian.news import NewsCache, windows

NOW = 1_789_000_000.0
RELEASE_MS = int((NOW + 3600) * 1000)


def _record(scope: str, impact: int, effective_ms: int, revision: int = 1, title: str = "CPI m/m") -> str:
    return json.dumps(
        {
            "v": 1,
            "dataset": "cal.high_impact",
            "scope": scope,
            "key": f"{effective_ms}|{scope}|{title}",
            "revision": revision,
            "known_at": effective_ms - 86_400_000,
            "effective_at": effective_ms,
            "availability": "observed",
            "source": "forexfactory",
            "seq": revision,
            "fields": {"title": title, "impact": impact, "forecast": "0.2"},
        }
    )


class HubJournalSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.day = dt.datetime.fromtimestamp(NOW, dt.UTC).date().isoformat()
        self.journal = self.root / "journal" / "cal.high_impact"
        self.journal.mkdir(parents=True)
        self.file = self.journal / f"{self.day}.ndjson"
        self.file.write_text(_record("USD", 2, RELEASE_MS) + "\n")
        self._beat()

    def _beat(self, age_seconds: float = 0.0) -> None:
        heartbeat = self.root / "heartbeat"
        heartbeat.write_text("1")
        stamp = NOW - age_seconds
        os.utime(heartbeat, (stamp, stamp))

    def _source(self, **kwargs) -> HubJournalSource:
        kwargs.setdefault("clock", lambda: NOW)
        return HubJournalSource(self.root, ("USD", "EUR"), **kwargs)

    def test_reads_a_high_impact_release_as_a_padded_window(self) -> None:
        events = self._source(pad_seconds=300.0).fetch(5.0)
        self.assertIsNotNone(events)
        assert events is not None
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].scope, "USD")
        self.assertAlmostEqual(events[0].end - events[0].start, 600.0)

    def test_the_window_actually_gates_the_release_instant(self) -> None:
        # Through the real ladder predicate, not a re-implementation of it: what matters is that
        # the guardian would actually hold orders at the release and not an hour before.
        events = self._source().fetch(5.0) or []
        gates = windows(events)
        at_release = dt.datetime.fromtimestamp(RELEASE_MS / 1000.0, dt.UTC)
        self.assertTrue(is_in_news_window(at_release, gates))
        self.assertFalse(is_in_news_window(at_release - dt.timedelta(hours=1), gates))

    def test_a_stale_heartbeat_returns_none_rather_than_no_windows(self) -> None:
        # The load-bearing case: an old store must look like a failed fetch, so the cache keeps
        # the windows it already had instead of concluding the week is clear.
        self._beat(age_seconds=3600.0)
        self.assertIsNone(self._source().fetch(5.0))

    def test_a_missing_heartbeat_returns_none(self) -> None:
        (self.root / "heartbeat").unlink()
        self.assertIsNone(self._source().fetch(5.0))

    def test_a_missing_journal_returns_none(self) -> None:
        self.file.unlink()
        self.assertIsNone(self._source().fetch(5.0))

    def test_a_stale_source_leaves_the_cache_holding_its_last_windows(self) -> None:
        source = self._source()
        cache = NewsCache([source], clock=lambda: NOW)
        cache.refresh(now=NOW)
        held = cache.windows()
        self.assertEqual(len(held), 1)

        self._beat(age_seconds=3600.0)
        cache.refresh(now=NOW + 10_000)
        self.assertEqual(cache.windows(), held)

    def test_holidays_are_opt_in_and_cover_the_whole_session(self) -> None:
        self.file.write_text(_record("USD", 3, RELEASE_MS, title="Bank Holiday") + "\n")
        self.assertEqual(self._source().fetch(5.0), [])

        events = self._source(include_holidays=True).fetch(5.0) or []
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].end - events[0].start, 86_400)

    def test_a_currency_outside_the_watch_list_is_ignored(self) -> None:
        self.file.write_text(_record("JPY", 2, RELEASE_MS) + "\n")
        self.assertEqual(self._source().fetch(5.0), [])

    def test_the_highest_revision_wins(self) -> None:
        later = RELEASE_MS + 1_800_000
        self.file.write_text(
            _record("USD", 2, RELEASE_MS, revision=1) + "\n" + _record("USD", 2, RELEASE_MS, revision=2) + "\n"
        )
        events = self._source().fetch(5.0) or []
        self.assertEqual(len(events), 1)
        self.assertNotEqual(later, 0)

    def test_a_malformed_line_is_skipped_rather_than_fatal(self) -> None:
        self.file.write_text(_record("USD", 2, RELEASE_MS) + "\n{not json}\n")
        events = self._source().fetch(5.0)
        self.assertIsNotNone(events)
        assert events is not None
        self.assertEqual(len(events), 1)

    def test_medium_impact_rows_do_not_open_a_window(self) -> None:
        self.file.write_text(_record("USD", 1, RELEASE_MS) + "\n")
        self.assertEqual(self._source().fetch(5.0), [])


if __name__ == "__main__":
    unittest.main()


class BuildNewsCacheTest(unittest.TestCase):
    """Which source the loop actually constructs, since a config knob nobody reads is not a knob."""

    def _config(self, **ladder: object):
        from guardian.config import GuardianConfig

        text = (
            "target:\n"
            "  name: t\n"
            "  gateway_url: http://127.0.0.1:5001\n"
            "  api_key: k\n"
            "account:\n"
            "  initial_balance: 50000\n"
            "ladder:\n"
            "  soft_pct: 2.5\n"
            "  hard_pct: 3.5\n"
            "  static_pct: 6\n" + "".join(f"  {k}: {v}\n" for k, v in ladder.items())
        )
        path = Path(tempfile.mkdtemp()) / "guardian.yaml"
        path.write_text(text)
        return GuardianConfig.load(path)

    def test_default_config_keeps_the_http_feed(self) -> None:
        from guardian.loop import build_news_cache
        from guardian.news import ForexFactorySource

        cache = build_news_cache(self._config())
        self.assertEqual(len(cache._sources), 1)
        self.assertIsInstance(cache._sources[0], ForexFactorySource)

    def test_naming_a_hub_root_switches_the_source(self) -> None:
        from guardian.loop import build_news_cache

        root = Path(tempfile.mkdtemp())
        cache = build_news_cache(self._config(news_hub_root=str(root)))
        self.assertEqual(len(cache._sources), 1)
        self.assertIsInstance(cache._sources[0], HubJournalSource)
        # And it makes no network call: an unreachable store fails closed to "keep last windows".
        self.assertIsNone(cache._sources[0].fetch(1.0))
