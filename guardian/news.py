"""Event windows that open the NEWS rung, and the sources that supply them.

The ladder needs exactly one thing from this module: the set of UTC intervals during which
new orders are unsafe. Everything else -- which provider, which fields, how a row becomes an
interval -- lives behind `Source`, so a second provider (another calendar, earnings, a
scheduled report) is a new transformer, not a change to the ladder or the cache.

    Source.fetch(timeout) -> list[Event] | None      one provider, one transformer
    Event(start, end, scope, severity, source)       what actually influences the decision
    windows(events) -> ((start, end), ...)           what the ladder consumes

An `Event` carries its own window. A release is a point padded on both sides; a bank
holiday is a whole session; an earnings call is however long the provider says. The ladder
does not know or care which -- it asks "is now inside any window".

Fetching runs on a background thread. The guard loop's job is to watch equity every few
seconds; a third-party CDN that hangs must never delay that, so `windows()` returns the
last successful result immediately and never blocks. A failed fetch keeps that source's
last-known events -- losing the feed does not remove protection you already had -- and
retries sooner than the normal cadence. Sources fail independently: one dead provider does
not blank the others.

ForexFactory, the one provider today, has three traps that are pinned by tests:
- `country` is a CURRENCY code (USD, EUR, ...) plus the literal `All`.
- `date` is ISO 8601 WITH a New York UTC offset; a 08:15 EDT release is 12:15 UTC.
- `impact` is exactly one of `High`, `Medium`, `Low`, `Holiday`.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from guardian.ladder import Window
from guardian.logging import log

DEFAULT_CURRENCIES: tuple[str, ...] = ("USD", "EUR")

SEVERITY_HIGH = "high"
SEVERITY_HOLIDAY = "holiday"


@dataclass(frozen=True)
class Event:
    """One thing that makes trading unsafe for a while.

    `start`/`end` are UTC epoch seconds and are the only fields the ladder reads. `scope`
    (a currency, a symbol, `ALL`) and `severity` are what a source filtered on, kept so a
    log line or a future rule can say why a window exists. `source` names the provider."""

    start: float
    end: float
    scope: str
    severity: str
    source: str
    title: str = ""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"event window ends before it starts: {self!r}")


class Source(Protocol):
    """A provider of events. `fetch` returns None on failure (the cache keeps the previous
    result) and a list -- possibly empty -- on success. It must not raise for bad data."""

    @property
    def name(self) -> str: ...

    def fetch(self, timeout_seconds: float) -> list[Event] | None: ...


def windows(events: Iterable[Event]) -> tuple[Window, ...]:
    """Sorted, de-duplicated (start, end) intervals. Several releases at the same minute
    (CPI m/m + y/y + core) collapse to one window."""
    return tuple(sorted({(e.start, e.end) for e in events}))


# -- ForexFactory ------------------------------------------------------------------------------

FOREXFACTORY_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def _parse_when(raw: object) -> dt.datetime | None:
    """A ForexFactory `date` -> aware datetime, or None when it is not a usable timestamp.

    Rejects a naive datetime outright: the feed always carries an offset, and a bare
    `2026-09-10T08:15:00` would be read as local time by `.timestamp()`, which on a UTC
    host silently shifts every window by the New York offset."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def forexfactory_events(
    payload: object,
    currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
    include_holidays: bool = False,
    pad_seconds: float = 300.0,
) -> list[Event]:
    """Pure transformer: a ForexFactory weekly payload -> events for `currencies`.

    `High` rows become a point padded by `pad_seconds` on each side. `Holiday` rows (opt-in)
    become the whole calendar day in the feed's own offset -- the row is stamped 00:00 with
    no duration, and a bank holiday is a session-long liquidity hazard, not a five-minute
    one. Malformed rows -- not a dict, missing/unparseable date, unknown impact -- are
    skipped one at a time, never fatal; a payload that is not a list yields nothing."""
    if not isinstance(payload, list):
        return []
    wanted = {c.strip().upper() for c in currencies if c.strip()}
    severities = {SEVERITY_HIGH, SEVERITY_HOLIDAY} if include_holidays else {SEVERITY_HIGH}
    out: list[Event] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        severity = str(row.get("impact", "")).strip().lower()
        if severity not in severities:
            continue
        scope = str(row.get("country", "")).strip().upper()
        if scope not in wanted:
            continue
        when = _parse_when(row.get("date"))
        if when is None:
            continue
        title = str(row.get("title", "")).strip()
        if severity == SEVERITY_HOLIDAY:
            day_start = when.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            out.append(Event(day_start, day_start + 86_400, scope, severity, "forexfactory", title))
        else:
            centre = when.timestamp()
            out.append(Event(centre - pad_seconds, centre + pad_seconds, scope, severity, "forexfactory", title))
    return out


def event_timestamps(
    events: object,
    currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
    include_holidays: bool = False,
) -> list[float]:
    """Sorted, de-duplicated window centres for a ForexFactory payload. Kept for callers
    that reason about release times rather than windows."""
    centres = {(e.start + e.end) / 2 for e in forexfactory_events(events, currencies, include_holidays, 0.0)}
    return sorted(centres)


def high_impact_timestamps(events: object, currencies: tuple[str, ...] = DEFAULT_CURRENCIES) -> list[float]:
    """Backward-compatible name for `event_timestamps` without holidays."""
    return event_timestamps(events, currencies, include_holidays=False)


class ForexFactorySource:
    name = "forexfactory"

    def __init__(
        self,
        feed_url: str = FOREXFACTORY_FEED,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
        *,
        include_holidays: bool = False,
        pad_seconds: float = 300.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._feed_url = feed_url
        self._currencies = currencies
        self._include_holidays = include_holidays
        self._pad = pad_seconds
        self._open = opener

    def fetch(self, timeout_seconds: float) -> list[Event] | None:
        try:
            req = urllib.request.Request(self._feed_url, headers={"User-Agent": "Mozilla/5.0 (guardian)"})
            with self._open(req, timeout=timeout_seconds) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
            log(f"news[{self.name}] fetch error:", e)
            return None
        if not isinstance(payload, list):
            log(f"news[{self.name}] fetch error: expected a JSON array, got {type(payload).__name__}")
            return None
        return forexfactory_events(payload, self._currencies, self._include_holidays, self._pad)


# -- the cache ---------------------------------------------------------------------------------


class _SourceState:
    def __init__(self) -> None:
        self.events: list[Event] | None = None
        self.next_due: float = 0.0


class NewsCache:
    """Keeps every source's events fresh without ever blocking the caller.

    `windows()` is O(sources) and lock-cheap: it merges whatever each source's last
    successful fetch produced. Refreshing is done by `refresh()` -- synchronously when
    called directly (tests, the smoke path), or on the daemon thread `start()` spawns.

    Cadence per source: `refresh_steady` after a success, `retry` after a failure. There
    is no separate "until first success" interval -- that existed only because the old
    cache shared one timer between the two outcomes, which is how a failed startup fetch
    used to leave the rung unarmed for an hour.
    """

    def __init__(
        self,
        sources: Iterable[Source],
        *,
        timeout_seconds: float = 30.0,
        refresh_steady_seconds: float = 6 * 3600.0,
        retry_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sources: list[Source] = list(sources)
        self._timeout = timeout_seconds
        self._refresh_steady = refresh_steady_seconds
        self._retry = retry_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, _SourceState] = {s.name: _SourceState() for s in self._sources}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._armed_event = threading.Event()

    # -- reading -------------------------------------------------------------------------

    def windows(self) -> tuple[Window, ...]:
        """Every source's last-known windows, merged. Never blocks, never fetches."""
        with self._lock:
            events = [e for st in self._state.values() if st.events for e in st.events]
        return windows(events)

    @property
    def unarmed(self) -> tuple[str, ...]:
        """Sources that have not had a single successful fetch yet."""
        with self._lock:
            return tuple(name for name, st in self._state.items() if st.events is None)

    @property
    def armed(self) -> bool:
        """True once every source has succeeded at least once (an empty week still counts)."""
        return not self.unarmed

    # -- refreshing ----------------------------------------------------------------------

    def refresh(self, now: float | None = None) -> bool:
        """Fetch every source that is due. Returns True when at least one fetch succeeded."""
        now = self._clock() if now is None else now
        with self._lock:
            due = [s for s in self._sources if now >= self._state[s.name].next_due]
        any_ok = False
        for source in due:
            fetched = source.fetch(self._timeout)
            with self._lock:
                st = self._state[source.name]
                if fetched is None:
                    st.next_due = now + self._retry
                    continue
                st.events = fetched
                st.next_due = now + self._refresh_steady
            any_ok = True
            log(f"news[{source.name}]: {len(windows(fetched))} window(s) this week")
        if self.armed:
            self._armed_event.set()
        return any_ok

    def start(self, arm_timeout_seconds: float | None = None) -> None:
        """Start the refresh thread, then wait up to `arm_timeout_seconds` (default: one fetch
        timeout) for every source to arm. The wait is bounded regardless of how many sources
        there are, so a slow provider cannot hold up the first guard cycle. Idempotent."""
        if self._thread is not None:
            return
        with self._lock:
            for st in self._state.values():
                st.next_due = 0.0
        self._thread = threading.Thread(target=self._run, name="guardian-news", daemon=True)
        self._thread.start()
        budget = self._timeout if arm_timeout_seconds is None else arm_timeout_seconds
        self._armed_event.wait(budget)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception as e:  # noqa: BLE001 -- the feed must never take the guard down
                log("news refresh error:", e)
                with self._lock:
                    for st in self._state.values():
                        st.next_due = self._clock() + self._retry
            with self._lock:
                soonest = min((st.next_due for st in self._state.values()), default=self._clock() + 60.0)
                wait = max(1.0, soonest - self._clock())
            self._stop.wait(min(wait, 60.0))
