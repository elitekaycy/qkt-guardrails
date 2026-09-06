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


def _as_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "false", "no"):
        return value.strip().lower() in ("true", "yes")
    raise ConfigError(f"'{field_name}' must be true or false, got {value!r}")


def parse_hhmm(value: str, field_name: str) -> tuple[int, int]:
    """'HH:MM' (24h UTC) -> (hour, minute); anything else is a config error."""
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value.strip())
    if m is None:
        raise ConfigError(f"'{field_name}' must be HH:MM in 24h UTC, got {value!r}")
    return int(m.group(1)), int(m.group(2))


def _typed_kwargs(raw: dict[str, object], types: dict[str, type], section_name: str) -> dict[str, object]:
    """Coerces a raw parsed section's values to the declared dataclass field types.

    An unknown key is a config error, not a silent no-op: a typo such as `soft_pcnt` would
    otherwise leave the threshold at its default while the operator believes it is set."""
    unknown = sorted(k for k in raw if k not in types)
    if unknown:
        raise ConfigError(f"unknown key(s) in '{section_name}:': {', '.join(unknown)}")
    out: dict[str, object] = {}
    for key, value in raw.items():
        if value is None:
            continue
        kind = types[key]
        field_name = f"{section_name}.{key}"
        if kind is float:
            out[key] = _as_float(value, field_name)
        elif kind is int:
            out[key] = _as_int(value, field_name)
        elif kind is bool:
            out[key] = _as_bool(value, field_name)
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
    # Comma-separated ForexFactory country codes whose high-impact events open a NEWS window.
    news_currencies: str = "USD,EUR"
    fri_flat_utc: int = 20
    # The WEEKEND rung is a market-calendar rule for instruments that CLOSE over the weekend
    # (FX, metals, indices). The kill switch is account-global, so a book that trades 24/7
    # instruments (crypto) must run on its own account with friday_flat: false and rely on the
    # engine's per-symbol session calendar instead -- there is no per-symbol weekend flatten.
    friday_flat: bool = True
    # When the weekend window ends (Sunday, HH:MM UTC). Brokers reopen at different times:
    # Exness/IC Markets ~22:05, The5ers 22:10; set it to your venue's first tradable minute.
    weekend_release_utc: str = "22:10"
    # ForexFactory marks bank holidays with impact "Holiday" rather than a High/Medium/Low
    # rating. Off by default (the historical behaviour); on, a holiday for a configured
    # currency opens a NEWS window like a high-impact release, so a thin-liquidity session
    # is treated as a hazard rather than ignored.
    news_include_holidays: bool = False
    # Feed fetch timeout. The fetch runs on a background thread, never on the guard loop.
    news_timeout_seconds: float = 30.0
    # Refresh cadence: every 6 hours after a successful fetch. After a FAILED fetch the next
    # attempt is `news_retry_seconds` away, not a full interval, so a transient feed outage at
    # startup does not leave the NEWS rung unarmed for an hour (the old cache shared one timer
    # between success and failure).
    news_refresh_steady_seconds: int = 6 * 3600
    news_retry_seconds: int = 300

    def __post_init__(self) -> None:
        if not (0 < self.soft_pct < self.hard_pct < self.static_pct):
            raise ConfigError("ladder thresholds must satisfy 0 < soft_pct < hard_pct < static_pct")
        if not (0 <= self.roll_utc_hour < 24):
            raise ConfigError("ladder.roll_utc_hour must be in [0, 24)")
        if not (0 <= self.fri_flat_utc < 24):
            raise ConfigError("ladder.fri_flat_utc must be in [0, 24)")
        if self.news_pad_min < 0:
            raise ConfigError("ladder.news_pad_min must be >= 0")
        if not self.news_currency_codes:
            raise ConfigError("ladder.news_currencies must list at least one currency code")
        parse_hhmm(self.weekend_release_utc, "ladder.weekend_release_utc")
        if self.news_timeout_seconds <= 0:
            raise ConfigError("ladder.news_timeout_seconds must be positive")
        for name in ("news_refresh_steady_seconds", "news_retry_seconds"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"ladder.{name} must be positive")

    @property
    def news_currency_codes(self) -> tuple[str, ...]:
        return tuple(c.strip().upper() for c in self.news_currencies.split(",") if c.strip())

    @property
    def weekend_release(self) -> tuple[int, int]:
        return parse_hhmm(self.weekend_release_utc, "ladder.weekend_release_utc")


@dataclass(frozen=True)
class NotifyConfig:
    telegram_token: str = ""
    telegram_chat: str = ""
    # Alerts are best-effort and off the critical path, but a hung Telegram call still delays
    # the cycle that raised it; keep this short.
    telegram_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.telegram_timeout_seconds <= 0:
            raise ConfigError("notify.telegram_timeout_seconds must be positive")

    @property
    def enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat)


DEFAULT_GATEWAY_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class PollConfig:
    interval_seconds: int = 30
    # Per-request timeout for the two gateway calls a cycle makes (/account, /health). A cycle
    # can therefore take up to 2x this before it sleeps, which is why the timeout may not be
    # longer than the interval: a 10s poll with a 20s timeout is not a 10s poll.
    #
    # Unset, it is min(20, interval_seconds) -- 20s was the hard-coded value, and capping it at
    # the interval means a config with a short poll keeps starting after the upgrade instead of
    # being refused for a timeout it never wrote. An EXPLICIT value longer than the interval is
    # still an error: that one the operator did write.
    gateway_timeout_seconds: float | None = None
    # Consecutive failed polls before the guardian declares itself BLIND (alert once, and
    # once more when sight returns). With the defaults that is 90s of not seeing equity.
    blind_after_failures: int = 3

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ConfigError("poll.interval_seconds must be positive")
        if self.gateway_timeout_seconds is None:
            object.__setattr__(
                self, "gateway_timeout_seconds", min(DEFAULT_GATEWAY_TIMEOUT_SECONDS, float(self.interval_seconds))
            )
        elif self.gateway_timeout_seconds <= 0:
            raise ConfigError("poll.gateway_timeout_seconds must be positive")
        elif self.gateway_timeout_seconds > self.interval_seconds:
            raise ConfigError(
                "poll.gateway_timeout_seconds must not exceed poll.interval_seconds "
                f"({self.gateway_timeout_seconds} > {self.interval_seconds}): a slow gateway would "
                "stretch every cycle past the interval you asked for"
            )
        if self.blind_after_failures < 1:
            raise ConfigError("poll.blind_after_failures must be >= 1")

    @property
    def gateway_timeout(self) -> float:
        """The resolved timeout, always a float once constructed."""
        assert self.gateway_timeout_seconds is not None
        return self.gateway_timeout_seconds


@dataclass(frozen=True)
class HealthConfig:
    # The container healthcheck reads the state file's age; it is unhealthy after this many
    # poll intervals without a saved cycle. Must cover a BLIND stretch or Docker restarts the
    # guardian right when it is trying to report the outage.
    stale_cycles: int = 3

    def __post_init__(self) -> None:
        if self.stale_cycles < 1:
            raise ConfigError("health.stale_cycles must be >= 1")


@dataclass(frozen=True)
class GuardianConfig:
    target: TargetConfig
    account: AccountConfig
    ladder: LadderConfig = field(default_factory=LadderConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    poll: PollConfig = field(default_factory=PollConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
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
            "news_currencies": str,
            "fri_flat_utc": int,
            "friday_flat": bool,
            "weekend_release_utc": str,
            "news_include_holidays": bool,
            "news_timeout_seconds": float,
            "news_refresh_steady_seconds": int,
            "news_retry_seconds": int,
        }
        # _typed_kwargs already validates each value against ladder_types/notify_types/
        # poll_types above at runtime; mypy can't correlate a dict[str, object] unpack
        # to a dataclass's per-field types, so these three are a deliberate, narrowly
        # scoped exception to the strict-typing rule, not a suppressed real bug.
        ladder = LadderConfig(**_typed_kwargs(ladder_raw, ladder_types, "ladder"))  # type: ignore[arg-type]

        notify_raw = _section(doc, "notify", required=False)
        notify_types: dict[str, type] = {
            "telegram_token": str,
            "telegram_chat": str,
            "telegram_timeout_seconds": float,
        }
        notify = NotifyConfig(**_typed_kwargs(notify_raw, notify_types, "notify"))  # type: ignore[arg-type]

        poll_raw = _section(doc, "poll", required=False)
        poll_types: dict[str, type] = {
            "interval_seconds": int,
            "gateway_timeout_seconds": float,
            "blind_after_failures": int,
        }
        poll = PollConfig(**_typed_kwargs(poll_raw, poll_types, "poll"))  # type: ignore[arg-type]

        health_raw = _section(doc, "health", required=False)
        health_types: dict[str, type] = {"stale_cycles": int}
        health = HealthConfig(**_typed_kwargs(health_raw, health_types, "health"))  # type: ignore[arg-type]

        state_raw = _section(doc, "state", required=False)
        state_path_raw = state_raw.get("path")
        state_path = _as_str(state_path_raw, "state.path") if state_path_raw is not None else "/state/guardian.json"

        return GuardianConfig(
            target=target,
            account=account,
            ladder=ladder,
            notify=notify,
            poll=poll,
            health=health,
            state_path=state_path,
        )
