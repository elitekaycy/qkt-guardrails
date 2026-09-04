"""High-impact news windows for the configured currencies, from the weekly ForexFactory feed."""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request

from guardian.logging import log

_REFRESH_SECONDS_INITIAL = 3600
_REFRESH_SECONDS_STEADY = 6 * 3600

DEFAULT_CURRENCIES: tuple[str, ...] = ("USD", "EUR")


def high_impact_timestamps(events: object, currencies: tuple[str, ...] = DEFAULT_CURRENCIES) -> list[float]:
    """Pure: sorted UNIX timestamps of the high-impact events for `currencies` in a
    ForexFactory weekly payload. Malformed rows are skipped, never fatal."""
    if not isinstance(events, list):
        return []
    wanted = {c.upper() for c in currencies}
    out: list[float] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("impact", "")).lower() != "high":
            continue
        if str(event.get("country", "")).upper() not in wanted:
            continue
        try:
            out.append(dt.datetime.fromisoformat(str(event["date"])).timestamp())
        except (KeyError, ValueError):
            continue
    return sorted(out)


def fetch(
    feed_url: str,
    currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
    timeout_seconds: float = 30.0,
) -> list[float] | None:
    """Returns this week's high-impact event timestamps for `currencies`, or None on
    a fetch failure (caller should keep the last-known list)."""
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (guardian)"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            events = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log("news feed error:", e)
        return None
    return high_impact_timestamps(events, currencies)


class NewsCache:
    """Refreshes hourly until a first successful fetch, then every 6 hours."""

    def __init__(self, feed_url: str, currencies: tuple[str, ...] = DEFAULT_CURRENCIES) -> None:
        self._feed_url = feed_url
        self._currencies = currencies
        self._events: list[float] | None = None
        self._fetched_at: float = 0.0

    def events(self) -> list[float] | None:
        due = _REFRESH_SECONDS_INITIAL if self._events is None else _REFRESH_SECONDS_STEADY
        if time.time() - self._fetched_at > due:
            self._fetched_at = time.time()
            fetched = fetch(self._feed_url, self._currencies)
            if fetched is not None:
                self._events = fetched
                log(f"news feed: {len(fetched)} high-impact {'/'.join(self._currencies)} events this week")
        return self._events
