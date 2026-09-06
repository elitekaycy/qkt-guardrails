"""Every runtime constant is configurable, every default matches the pre-0.3 behaviour,
and every bad value fails at load rather than at the moment it matters."""
import os
import tempfile
import unittest
from pathlib import Path

from guardian.config import ConfigError, GuardianConfig, HealthConfig, LadderConfig, NotifyConfig, PollConfig
from guardian.healthcheck import main as healthcheck_main
from guardian.loop import Sight, build_news_cache

MINIMAL = """
target:
  name: t
  gateway_url: http://gw:5001
  api_key: k
account:
  initial_balance: 50000
"""


def _write(text: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    Path(path).write_text(text)
    return Path(path)


class DefaultsTest(unittest.TestCase):
    """The fallbacks are the numbers the guardian ran with before they were configurable."""

    def test_defaults_match_the_historical_constants(self) -> None:
        cfg = GuardianConfig.load(_write(MINIMAL))
        self.assertEqual(cfg.poll.interval_seconds, 30)
        self.assertEqual(cfg.poll.gateway_timeout, 20.0)
        self.assertEqual(cfg.poll.blind_after_failures, 3)
        self.assertEqual(cfg.health.stale_cycles, 3)
        self.assertEqual(cfg.notify.telegram_timeout_seconds, 10.0)
        self.assertEqual(cfg.ladder.news_timeout_seconds, 30.0)
        self.assertEqual(cfg.ladder.news_refresh_steady_seconds, 6 * 3600)
        self.assertEqual(cfg.ladder.news_retry_seconds, 300)
        self.assertFalse(cfg.ladder.news_include_holidays)

    def test_every_example_config_loads(self) -> None:
        examples = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.yaml"))
        self.assertTrue(examples)
        for var in ("GUARDIAN_CHANGE_ME_API_KEY", "TG_TOKEN", "TG_CHAT"):
            os.environ.setdefault(var, "x")
        for path in examples:
            with self.subTest(example=path.name):
                GuardianConfig.load(path)


class OverridesTest(unittest.TestCase):
    def test_every_runtime_knob_is_settable_from_yaml(self) -> None:
        cfg = GuardianConfig.load(_write(MINIMAL + """
ladder:
  news_include_holidays: true
  news_timeout_seconds: 8.5
  news_refresh_steady_seconds: 1800
  news_retry_seconds: 60
notify:
  telegram_timeout_seconds: 4
poll:
  interval_seconds: 10
  gateway_timeout_seconds: 5
  blind_after_failures: 6
health:
  stale_cycles: 5
"""))
        self.assertTrue(cfg.ladder.news_include_holidays)
        self.assertEqual(cfg.ladder.news_timeout_seconds, 8.5)
        self.assertEqual(cfg.ladder.news_refresh_steady_seconds, 1800)
        self.assertEqual(cfg.ladder.news_retry_seconds, 60)
        self.assertEqual(cfg.notify.telegram_timeout_seconds, 4.0)
        self.assertEqual(cfg.poll.interval_seconds, 10)
        self.assertEqual(cfg.poll.gateway_timeout, 5.0)
        self.assertEqual(cfg.poll.blind_after_failures, 6)
        self.assertEqual(cfg.health.stale_cycles, 5)

    def test_knobs_reach_the_objects_that_use_them(self) -> None:
        cfg = GuardianConfig.load(_write(MINIMAL + """
ladder:
  news_include_holidays: true
  news_timeout_seconds: 8
  news_retry_seconds: 60
poll:
  blind_after_failures: 2
"""))
        news = build_news_cache(cfg)
        (source,) = news._sources
        self.assertEqual(source.name, "forexfactory")
        self.assertTrue(source._include_holidays)
        self.assertEqual(source._pad, cfg.ladder.news_pad_min * 60)
        self.assertEqual(news._timeout, 8.0)
        self.assertEqual(news._retry, 60)
        sight = Sight(cfg.poll.blind_after_failures)
        self.assertIsNone(sight.failed(RuntimeError("1")))
        self.assertIsNotNone(sight.failed(RuntimeError("2")))   # blind at exactly 2


class ValidationTest(unittest.TestCase):
    def _bad(self, yaml: str, fragment: str) -> None:
        with self.assertRaises(ConfigError) as ctx:
            GuardianConfig.load(_write(MINIMAL + yaml))
        self.assertIn(fragment, str(ctx.exception))

    def test_explicit_timeout_longer_than_interval_is_rejected(self) -> None:
        self._bad("poll:\n  interval_seconds: 10\n  gateway_timeout_seconds: 20\n", "must not exceed")

    def test_timeout_equal_to_interval_is_allowed(self) -> None:
        cfg = GuardianConfig.load(_write(MINIMAL + "poll:\n  interval_seconds: 20\n  gateway_timeout_seconds: 20\n"))
        self.assertEqual(cfg.poll.gateway_timeout, 20.0)

    def test_unset_timeout_is_capped_at_the_interval(self) -> None:
        """The CI smoke config -- a 2s poll and no timeout -- was valid before and must stay
        valid: an upgrade may not refuse a config for a value it never wrote."""
        cfg = GuardianConfig.load(_write(MINIMAL + "poll:\n  interval_seconds: 2\n"))
        self.assertEqual(cfg.poll.gateway_timeout, 2.0)
        cfg = GuardianConfig.load(_write(MINIMAL + "poll:\n  interval_seconds: 30\n"))
        self.assertEqual(cfg.poll.gateway_timeout, 20.0)      # the historical value, unchanged

    def test_non_positive_values_are_rejected(self) -> None:
        self._bad("poll:\n  interval_seconds: 0\n", "poll.interval_seconds")
        self._bad("poll:\n  gateway_timeout_seconds: 0\n", "poll.gateway_timeout_seconds")
        self._bad("poll:\n  blind_after_failures: 0\n", "poll.blind_after_failures")
        self._bad("health:\n  stale_cycles: 0\n", "health.stale_cycles")
        self._bad("notify:\n  telegram_timeout_seconds: -1\n", "notify.telegram_timeout_seconds")
        self._bad("ladder:\n  news_timeout_seconds: 0\n", "ladder.news_timeout_seconds")
        self._bad("ladder:\n  news_retry_seconds: 0\n", "ladder.news_retry_seconds")
        self._bad("ladder:\n  news_refresh_steady_seconds: -5\n", "ladder.news_refresh_steady_seconds")
        self._bad("ladder:\n  news_pad_min: -1\n", "ladder.news_pad_min")

    def test_wrong_types_are_rejected(self) -> None:
        self._bad("ladder:\n  news_include_holidays: sometimes\n", "true or false")
        self._bad("poll:\n  blind_after_failures: three\n", "whole number")

    def test_unknown_key_is_an_error_not_a_silent_default(self) -> None:
        """`soft_pcnt: 1` must not leave soft_pct at 2.5 while the operator believes it is 1."""
        self._bad("ladder:\n  soft_pcnt: 1\n", "unknown key(s) in 'ladder:': soft_pcnt")
        self._bad("poll:\n  intervl: 5\n", "unknown key(s) in 'poll:'")

    def test_dataclasses_validate_when_built_directly_too(self) -> None:
        with self.assertRaises(ConfigError):
            PollConfig(interval_seconds=5, gateway_timeout_seconds=6)
        with self.assertRaises(ConfigError):
            HealthConfig(stale_cycles=0)
        with self.assertRaises(ConfigError):
            NotifyConfig(telegram_timeout_seconds=0)
        with self.assertRaises(ConfigError):
            LadderConfig(news_retry_seconds=0)


class HealthcheckTest(unittest.TestCase):
    def test_stale_threshold_uses_configured_cycles(self) -> None:
        state = _write("{}")

        def cfg_with(cycles: int) -> str:
            # A 1s poll needs a timeout no longer than 1s, or the load-time check rejects it.
            return MINIMAL + (
                "poll:\n  interval_seconds: 1\n  gateway_timeout_seconds: 1\n"
                f"health:\n  stale_cycles: {cycles}\nstate:\n  path: {state}\n"
            )

        cfg_path = _write(cfg_with(2))
        self.assertEqual(healthcheck_main([str(cfg_path)]), 0)
        old = os.path.getmtime(state) - 3          # 3s old > 1s x 2 cycles
        os.utime(state, (old, old))
        self.assertEqual(healthcheck_main([str(cfg_path)]), 1)
        cfg_path.write_text(cfg_with(5))
        self.assertEqual(healthcheck_main([str(cfg_path)]), 0)   # 3s old < 1s x 5 cycles


if __name__ == "__main__":
    unittest.main()
