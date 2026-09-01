import tempfile
import unittest
from pathlib import Path

from guardian.state import GuardianState


class LoadSaveTest(unittest.TestCase):
    def test_missing_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = GuardianState.load(Path(d) / "does-not-exist.json")
            self.assertEqual(state, GuardianState())

    def test_save_then_load_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            original = GuardianState(day="2026-06-01", prev_close=10_000.0, daily_lock=True, lock="daily")
            original.save(path)
            loaded = GuardianState.load(path)
            self.assertEqual(loaded, original)

    def test_corrupt_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text("{not json")
            self.assertEqual(GuardianState.load(path), GuardianState())

    def test_unknown_fields_in_file_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text('{"day": "2026-06-01", "from_a_future_version": 1}')
            state = GuardianState.load(path)
            self.assertEqual(state.day, "2026-06-01")


if __name__ == "__main__":
    unittest.main()
