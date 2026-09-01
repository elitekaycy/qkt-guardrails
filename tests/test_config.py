import os
import tempfile
import unittest
from pathlib import Path

from guardian.config import ConfigError, GuardianConfig

VALID = """
target:
  name: bot2-forward-bench
  gateway_url: http://mt5-gateway:5001
  api_key: ${TEST_GUARDIAN_API_KEY}

account:
  initial_balance: 50000

ladder:
  soft_pct: 2.5
  hard_pct: 3.5
  static_pct: 6

notify:
  telegram_token: ${TEST_GUARDIAN_TG_TOKEN}
  telegram_chat: "12345"
"""


class LoadTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        Path(path).write_text(text)
        self.addCleanup(os.unlink, path)
        return Path(path)

    def test_loads_a_valid_config_with_env_interpolation(self) -> None:
        os.environ["TEST_GUARDIAN_API_KEY"] = "secret-123"
        os.environ["TEST_GUARDIAN_TG_TOKEN"] = "tg-token"
        self.addCleanup(os.environ.pop, "TEST_GUARDIAN_API_KEY")
        self.addCleanup(os.environ.pop, "TEST_GUARDIAN_TG_TOKEN")

        cfg = GuardianConfig.load(self._write(VALID))

        self.assertEqual(cfg.target.name, "bot2-forward-bench")
        self.assertEqual(cfg.target.api_key, "secret-123")
        self.assertEqual(cfg.account.initial_balance, 50000.0)
        self.assertEqual(cfg.ladder.soft_pct, 2.5)
        self.assertTrue(cfg.notify.enabled)
        self.assertEqual(cfg.state_path, "/state/guardian.json")

    def test_missing_env_var_referenced_by_config_raises(self) -> None:
        os.environ.pop("TEST_GUARDIAN_UNSET", None)
        text = VALID.replace("${TEST_GUARDIAN_API_KEY}", "${TEST_GUARDIAN_UNSET}")
        os.environ["TEST_GUARDIAN_TG_TOKEN"] = "tg-token"
        self.addCleanup(os.environ.pop, "TEST_GUARDIAN_TG_TOKEN")
        with self.assertRaises(ConfigError):
            GuardianConfig.load(self._write(text))

    def test_missing_target_section_raises(self) -> None:
        with self.assertRaises(ConfigError):
            GuardianConfig.load(self._write("account:\n  initial_balance: 1000\n"))

    def test_ladder_defaults_apply_when_section_omitted(self) -> None:
        os.environ["TEST_GUARDIAN_API_KEY"] = "k"
        self.addCleanup(os.environ.pop, "TEST_GUARDIAN_API_KEY")
        text = """
target:
  name: bot2
  gateway_url: http://mt5-gateway:5001
  api_key: ${TEST_GUARDIAN_API_KEY}
account:
  initial_balance: 1000
"""
        cfg = GuardianConfig.load(self._write(text))
        self.assertEqual(cfg.ladder.soft_pct, 2.5)
        self.assertFalse(cfg.notify.enabled)

    def test_inverted_ladder_thresholds_are_rejected(self) -> None:
        os.environ["TEST_GUARDIAN_API_KEY"] = "k"
        self.addCleanup(os.environ.pop, "TEST_GUARDIAN_API_KEY")
        text = """
target:
  name: bot2
  gateway_url: http://mt5-gateway:5001
  api_key: ${TEST_GUARDIAN_API_KEY}
account:
  initial_balance: 1000
ladder:
  soft_pct: 5
  hard_pct: 3
  static_pct: 6
"""
        with self.assertRaises(ConfigError):
            GuardianConfig.load(self._write(text))


if __name__ == "__main__":
    unittest.main()
