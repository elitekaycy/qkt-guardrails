"""A news source that reads a qkt-data-hub journal from disk instead of fetching a feed.

The guardian's NEWS rung needs one thing: the UTC windows during which new orders are unsafe.
Today it gets them by fetching a third-party CDN from inside the process that is supposed to stop
trading when everything else has failed. That is a network dependency in the brake, and the
observed failure of that feed -- an HTML error page served with a 200, parsing to zero events --
is exactly the shape that empties the windows while the system still looks healthy.

If a hub is already collecting that calendar on the same host, the guardian can read its journal
with nothing but the standard library: no HTTP, no new dependency, no shared secret, and the same
records the trading engine sees. This module is that source.

Two rules make it safe to substitute:

- **A stale store is a failure, not an empty week.** If the hub's heartbeat has stopped advancing,
  the journal on disk may be arbitrarily old, and returning its windows would quietly assert that
  no release is coming. `fetch` returns `None` instead, which makes `NewsCache` keep the last
  windows it had and retry sooner -- losing the feed never removes protection already held.
- **It reads, never writes.** The hub owns its store and is its only writer. Mount it read-only.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from guardian.logging import log
from guardian.news import SEVERITY_HIGH, SEVERITY_HOLIDAY, Event

#: Impact ordinals as the hub's `cal.high_impact` schema declares them.
_IMPACT_HIGH = 2
_IMPACT_HOLIDAY = 3

DEFAULT_DATASET = "cal.high_impact"
DEFAULT_STALE_AFTER_SECONDS = 900.0


class HubJournalSource:
    """Reads calendar events from a hub store's append-only journal.

    `currencies` filters by the hub's `scope`, which for this dataset is a currency code plus the
    literal `ALL`. `pad_seconds` and `include_holidays` mean exactly what they do for the HTTP
    source, so swapping one for the other changes where the windows come from and nothing else.
    """

    def __init__(
        self,
        root: str | Path,
        currencies: tuple[str, ...] = ("USD", "EUR"),
        *,
        dataset: str = DEFAULT_DATASET,
        include_holidays: bool = False,
        pad_seconds: float = 300.0,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        lookback_days: int = 3,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root)
        self._dataset = dataset
        self._currencies = {c.strip().upper() for c in currencies if c.strip()}
        self._include_holidays = include_holidays
        self._pad = pad_seconds
        self._stale_after = stale_after_seconds
        self._lookback_days = max(1, lookback_days)
        self._clock = clock

    @property
    def name(self) -> str:
        return f"hub:{self._dataset}"

    # -- liveness ------------------------------------------------------------------------

    def _heartbeat_age_seconds(self) -> float | None:
        """Seconds since the hub last beat, or None when it has never beaten at all."""
        heartbeat = self._root / "heartbeat"
        try:
            return self._clock() - heartbeat.stat().st_mtime
        except OSError:
            return None

    # -- reading -------------------------------------------------------------------------

    def _day_files(self) -> list[Path]:
        """The recent day files, newest last.

        Only the last few days are read: an event window is minutes wide and the rung only cares
        about what is imminent, so walking years of history on every refresh would cost time for
        nothing. A schedule published further ahead still arrives, because the hub re-journals it
        whenever the provider's answer changes.
        """
        directory = self._root / "journal" / self._dataset
        if not directory.is_dir():
            return []
        today = dt.datetime.fromtimestamp(self._clock(), dt.UTC).date()
        wanted = {(today - dt.timedelta(days=n)).isoformat() for n in range(self._lookback_days)}
        return sorted(p for p in directory.glob("*.ndjson") if p.stem in wanted)

    def fetch(self, timeout_seconds: float) -> list[Event] | None:
        """Current windows from the journal, or `None` when the store cannot be trusted.

        Never raises: the cache treats `None` as "keep what you had and retry sooner", which is
        how one unavailable source avoids taking the guard down with it.
        """
        age = self._heartbeat_age_seconds()
        if age is None:
            log(f"news[{self.name}] no heartbeat at {self._root}; keeping last known windows")
            return None
        if age > self._stale_after:
            log(f"news[{self.name}] heartbeat is {int(age)}s old (> {int(self._stale_after)}s); not trusting the store")
            return None

        files = self._day_files()
        if not files:
            log(f"news[{self.name}] no recent journal days under {self._root}")
            return None

        latest: dict[tuple[str, str], dict[str, object]] = {}
        skipped = 0
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                log(f"news[{self.name}] cannot read {path}: {e}")
                return None
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(record, dict):
                    skipped += 1
                    continue
                key = (str(record.get("scope", "")), str(record.get("key", "")))
                previous = latest.get(key)
                # Highest revision wins: a corrected release must not be shadowed by the row that
                # preceded it just because that row appears earlier in the file.
                if previous is None or (_as_int(record.get("revision")) or 1) >= (
                    _as_int(previous.get("revision")) or 1
                ):
                    latest[key] = record
        if skipped:
            log(f"news[{self.name}] skipped {skipped} unparseable line(s)")

        return self._to_events(latest.values())

    def _to_events(self, records: Iterable[dict[str, object]]) -> list[Event]:
        out: list[Event] = []
        for record in records:
            scope = str(record.get("scope", "")).strip().upper()
            if scope not in self._currencies and scope != "ALL":
                continue
            fields = record.get("fields")
            fields = fields if isinstance(fields, dict) else {}
            impact = _as_int(fields.get("impact"))
            if impact is None:
                continue
            effective_at = _as_int(record.get("effective_at"))
            if effective_at is None:
                continue
            centre = effective_at / 1000.0
            title = str(fields.get("title", "") or "")
            if impact == _IMPACT_HOLIDAY:
                if not self._include_holidays:
                    continue
                # A bank holiday is a session-long liquidity hazard, not a five-minute one, so the
                # window is the whole UTC day the hub stamped it on.
                day_start = dt.datetime.fromtimestamp(centre, dt.UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                start = day_start.timestamp()
                out.append(Event(start, start + 86_400, scope, SEVERITY_HOLIDAY, self.name, title))
            elif impact == _IMPACT_HIGH:
                out.append(Event(centre - self._pad, centre + self._pad, scope, SEVERITY_HIGH, self.name, title))
        return out


def _as_int(value: object) -> int | None:
    """A hub field as an int, tolerating the decimal-string form numbers travel in."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None
