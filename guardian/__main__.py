"""Entrypoint: `python -m guardian --config /path/to/account.yaml`."""
from __future__ import annotations

import argparse
import sys

from guardian.config import ConfigError, GuardianConfig
from guardian.loop import run_forever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian")
    parser.add_argument("--config", required=True, help="path to this account's guardian YAML config")
    args = parser.parse_args(argv)

    try:
        cfg = GuardianConfig.load(args.config)
    except (ConfigError, OSError) as e:
        print(f"guardian: {e}", file=sys.stderr)
        return 1

    run_forever(cfg)
    return 0  # pragma: no cover — run_forever loops until the process is killed


if __name__ == "__main__":
    raise SystemExit(main())
