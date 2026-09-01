"""Docker HEALTHCHECK: the guardian is alive if it has saved state recently.

No HTTP server to poll (the guardian only talks outbound, to the gateway) —
so liveness is "the state file's mtime is newer than a few missed poll
cycles," which also catches a process that's up but wedged in a stuck call.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from guardian.config import ConfigError, GuardianConfig

_STALE_CYCLES = 3


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: healthcheck.py <config-path>", file=sys.stderr)
        return 2
    try:
        cfg = GuardianConfig.load(argv[0])
    except (ConfigError, OSError) as e:
        print(f"healthcheck: {e}", file=sys.stderr)
        return 2

    state_file = Path(cfg.state_path)
    if not state_file.exists():
        # First cycle hasn't landed yet — not unhealthy, just starting.
        return 0

    age = time.time() - state_file.stat().st_mtime
    stale_after = cfg.poll.interval_seconds * _STALE_CYCLES
    if age > stale_after:
        print(f"healthcheck: state is {age:.0f}s old, stale after {stale_after}s", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
