"""High-impact USD/EUR news windows, from the weekly ForexFactory calendar feed."""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request

from guardian.logging import log

_REFRESH_SECONDS_INITIAL = 3600
_REFRESH_SECONDS_STEADY = 6 * 3600


def fetch(feed_url: str, timeout_seconds: float = 30.0) -> list[float] | None:
    """Returns sorted UNIX timestamps of this week's high-impact USD/EUR events,
    or None on a fetch failure (caller should keep the last-known list)."""
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (guardian)"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            events = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log("news feed error:", e)
        return None

    out: list[float] = []
    for event in events:
        if str(event.get("impact", "")).lower() != "high":
            continue
        if event.get("country") not in ("USD", "EUR"):
            continue
        try:
            out.append(dt.datetime.fromisoformat(event["date"]).timestamp())
        except (KeyError, ValueError):
            continue
    return sorted(out)


class NewsCache:
    """Refreshes hourly until a first successful fetch, then every 6 hours."""

    def __init__(self, feed_url: str) -> None:
        self._feed_url = feed_url
        self._events: list[float] | None = None
        self._fetched_at: float = 0.0

    def events(self) -> list[float] | None:
        due = _REFRESH_SECONDS_INITIAL if self._events is None else _REFRESH_SECONDS_STEADY
        if time.time() - self._fetched_at > due:
            self._fetched_at = time.time()
            fetched = fetch(self._feed_url)
            if fetched is not None:
                self._events = fetched
                log(f"news feed: {len(fetched)} high-impact USD/EUR events this week")
        return self._events
