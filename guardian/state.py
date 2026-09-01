"""Guardian state, persisted to disk so a container restart doesn't forget
today's rollover anchor, the static lock, or which kill switch it owns."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GuardianState:
    day: str | None = None
    prev_close: float | None = None
    equity_now: float | None = None
    daily_lock: bool = False
    lock: str | None = None
    fri_flat: str | None = None
    guard_kill: bool = False

    @staticmethod
    def load(path: str | Path) -> GuardianState:
        p = Path(path)
        if not p.exists():
            return GuardianState()
        try:
            raw = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return GuardianState()
        known = {f for f in GuardianState.__dataclass_fields__}
        return GuardianState(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self)))
        tmp.replace(p)
