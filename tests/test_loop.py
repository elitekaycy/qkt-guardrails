"""run_once must treat a payload without positive equity as a gateway error —
never as a drawdown. equity 0.0 reads as 'below the static floor' and would
flatten the whole book on a telemetry glitch."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from guardian.config import AccountConfig, GuardianConfig, TargetConfig
from guardian.gateway import GatewayError
from guardian.loop import BLIND_AFTER_FAILURES, Sight, run_once
from guardian.state import GuardianState


class FakeGateway:
    def __init__(self, account_payload: dict) -> None:
        self._account = account_payload
        self.killed = False
        self.flattened = False

    def account(self) -> dict:
        return self._account

    def kill_switch_active(self) -> bool:
        return False

    def kill(self, flatten: bool) -> None:
        self.killed = True
        self.flattened = flatten

    def release(self) -> None:
        pass


class NoNews:
    def events(self) -> list[float]:
        return []


class NoNotify:
    def send(self, _message: str) -> None:
        pass


BAD_PAYLOADS = [
    {},
    {"equity": None},
    {"equity": 0},
    {"equity": 0.0},
    {"equity": "nan-ish"},
    {"equity": -5},
]


def _cfg(tmp_dir: str) -> GuardianConfig:
    return GuardianConfig(
        target=TargetConfig(name="t", gateway_url="http://x", api_key="k"),
        account=AccountConfig(initial_balance=50000),
        state_path=str(Path(tmp_dir) / "state.json"),
    )


class BadEquityTest(unittest.TestCase):
    def test_bad_equity_is_a_gateway_error_not_a_flatten(self) -> None:
        for payload in BAD_PAYLOADS:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                gateway = FakeGateway(payload)
                with self.assertRaises(GatewayError):
                    run_once(_cfg(tmp), gateway, NoNotify(), NoNews(), GuardianState())
                self.assertFalse(gateway.killed, "must never touch the kill switch on bad data")

    def test_valid_equity_still_evaluates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gateway = FakeGateway({"equity": 50000.0})
            # A Wednesday noon: clear of the weekend window, so the only thing that
            # could engage the kill switch here is the equity reading itself.
            wednesday = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)
            state = run_once(_cfg(tmp), gateway, NoNotify(), NoNews(), GuardianState(), now=wednesday)
            self.assertEqual(state.equity_now, 50000.0)
            self.assertFalse(gateway.killed)

    def test_weekend_window_engages_the_kill_switch_with_an_injected_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gateway = FakeGateway({"equity": 50000.0})
            saturday = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.UTC)
            run_once(_cfg(tmp), gateway, NoNotify(), NoNews(), GuardianState(), now=saturday)
            self.assertTrue(gateway.killed)


class SightTest(unittest.TestCase):
    def test_alerts_once_on_the_third_straight_failure(self) -> None:
        sight = Sight()
        err = GatewayError("GET /account failed: refused")
        alerts = [sight.failed(err) for _ in range(BLIND_AFTER_FAILURES + 2)]
        self.assertEqual([a is not None for a in alerts], [False, False, True, False, False])
        self.assertIn("BLIND: 3 polls failed", alerts[2] or "")
        self.assertIn("refused", alerts[2] or "")
        self.assertTrue(sight.blind)

    def test_single_hiccups_between_successes_stay_quiet(self) -> None:
        sight = Sight()
        for _ in range(3):
            self.assertIsNone(sight.failed(GatewayError("x")))
            self.assertIsNone(sight.succeeded())
        self.assertFalse(sight.blind)

    def test_announces_restored_sight_once_with_the_outage_length(self) -> None:
        sight = Sight()
        for _ in range(5):
            sight.failed(GatewayError("x"))
        self.assertEqual(sight.succeeded(), "sight restored after 5 failed polls")
        self.assertIsNone(sight.succeeded())
        self.assertFalse(sight.blind)

    def test_any_exception_counts_as_a_failed_poll(self) -> None:
        sight = Sight(blind_after=2)
        self.assertIsNone(sight.failed(ValueError("boom")))
        self.assertIsNotNone(sight.failed(RuntimeError("boom")))
