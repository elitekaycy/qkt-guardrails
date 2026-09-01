"""Typed config loaded from one guardian YAML file — one file, one account.

`${VAR}` in any string value is substituted from the process environment at
load time (matching qkt.config.yaml's own convention), so secrets never sit
in the config file itself.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from guardian.simpleyaml import SimpleYamlError, parse

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    pass


def _interpolate(value: object) -> object:
    if not isinstance(value, str):
        return value

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise ConfigError(f"config references ${{{name}}} but it is not set in the environment")
        return os.environ[name]

    return _ENV_REF.sub(sub, value)


def _section(doc: dict[str, object], name: str, required: bool = True) -> dict[str, object]:
    raw = doc.get(name)
    if raw is None:
        if required:
            raise ConfigError(f"missing required '{name}:' section")
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"'{name}:' must be a section, not a scalar value")
    return {k: _interpolate(v) for k, v in raw.items()}


def _require(section: dict[str, object], key: str, section_name: str) -> object:
    if key not in section or section[key] is None:
        raise ConfigError(f"missing required '{section_name}.{key}'")
    return section[key]


def _as_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"'{field_name}' must be a number, got {value!r}")
    try:
        return float(value)
    except ValueError as e:
        raise ConfigError(f"'{field_name}' must be a number, got {value!r}") from e


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"'{field_name}' must be a whole number, got {value!r}")
    try:
        return int(value)
    except ValueError as e:
        raise ConfigError(f"'{field_name}' must be a whole number, got {value!r}") from e


def _as_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"'{field_name}' must be text, got {value!r}")
    return value


def _typed_kwargs(raw: dict[str, object], types: dict[str, type], section_name: str) -> dict[str, object]:
    """Coerces a raw parsed section's values to the declared dataclass field types."""
    out: dict[str, object] = {}
    for key, value in raw.items():
        if value is None or key not in types:
            continue
        kind = types[key]
        field_name = f"{section_name}.{key}"
        if kind is float:
            out[key] = _as_float(value, field_name)
        elif kind is int:
            out[key] = _as_int(value, field_name)
        else:
            out[key] = _as_str(value, field_name)
    return out


@dataclass(frozen=True)
class TargetConfig:
    """The mt5-gateway (and, by name, the qkt/EA instance behind it) this guardian watches."""

    name: str
    gateway_url: str
    api_key: str


@dataclass(frozen=True)
class AccountConfig:
    initial_balance: float


@dataclass(frozen=True)
class LadderConfig:
    soft_pct: float = 2.5
    hard_pct: float = 3.5
    static_pct: float = 6.0
    roll_utc_hour: int = 21
    news_pad_min: int = 5
    news_feed: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    fri_flat_utc: int = 20

    def __post_init__(self) -> None:
        if not (0 < self.soft_pct < self.hard_pct < self.static_pct):
            raise ConfigError("ladder thresholds must satisfy 0 < soft_pct < hard_pct < static_pct")
        if not (0 <= self.roll_utc_hour < 24):
            raise ConfigError("ladder.roll_utc_hour must be in [0, 24)")
        if not (0 <= self.fri_flat_utc < 24):
            raise ConfigError("ladder.fri_flat_utc must be in [0, 24)")


@dataclass(frozen=True)
class NotifyConfig:
    telegram_token: str = ""
    telegram_chat: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat)


@dataclass(frozen=True)
class PollConfig:
    interval_seconds: int = 30


@dataclass(frozen=True)
class GuardianConfig:
    target: TargetConfig
    account: AccountConfig
    ladder: LadderConfig = field(default_factory=LadderConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    poll: PollConfig = field(default_factory=PollConfig)
    state_path: str = "/state/guardian.json"

    @staticmethod
    def load(path: Path | str) -> GuardianConfig:
        text = Path(path).read_text()
        try:
            doc = parse(text)
        except SimpleYamlError as e:
            raise ConfigError(f"{path}: {e}") from e

        target_raw = _section(doc, "target")
        target = TargetConfig(
            name=_as_str(_require(target_raw, "name", "target"), "target.name"),
            gateway_url=_as_str(_require(target_raw, "gateway_url", "target"), "target.gateway_url"),
            api_key=_as_str(_require(target_raw, "api_key", "target"), "target.api_key"),
        )

        account_raw = _section(doc, "account")
        account = AccountConfig(
            initial_balance=_as_float(
                _require(account_raw, "initial_balance", "account"), "account.initial_balance"
            )
        )

        ladder_raw = _section(doc, "ladder", required=False)
        ladder_types: dict[str, type] = {
            "soft_pct": float,
            "hard_pct": float,
            "static_pct": float,
            "roll_utc_hour": int,
            "news_pad_min": int,
            "news_feed": str,
            "fri_flat_utc": int,
        }
        # _typed_kwargs already validates each value against ladder_types/notify_types/
        # poll_types above at runtime; mypy can't correlate a dict[str, object] unpack
        # to a dataclass's per-field types, so these three are a deliberate, narrowly
        # scoped exception to the strict-typing rule, not a suppressed real bug.
        ladder = LadderConfig(**_typed_kwargs(ladder_raw, ladder_types, "ladder"))  # type: ignore[arg-type]

        notify_raw = _section(doc, "notify", required=False)
        notify_types: dict[str, type] = {"telegram_token": str, "telegram_chat": str}
        notify = NotifyConfig(**_typed_kwargs(notify_raw, notify_types, "notify"))  # type: ignore[arg-type]

        poll_raw = _section(doc, "poll", required=False)
        poll_types: dict[str, type] = {"interval_seconds": int}
        poll = PollConfig(**_typed_kwargs(poll_raw, poll_types, "poll"))  # type: ignore[arg-type]

        state_raw = _section(doc, "state", required=False)
        state_path_raw = state_raw.get("path")
        state_path = _as_str(state_path_raw, "state.path") if state_path_raw is not None else "/state/guardian.json"

        return GuardianConfig(
            target=target,
            account=account,
            ladder=ladder,
            notify=notify,
            poll=poll,
            state_path=state_path,
        )
