"""One-line UTC-timestamped logging to stdout — no framework, containers capture stdout."""
from __future__ import annotations

import datetime as dt


def log(*args: object) -> None:
    stamp = dt.datetime.now(dt.UTC).strftime("%m-%d %H:%M:%S")
    print(stamp, *args, flush=True)
