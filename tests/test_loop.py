"""run_once must treat a payload without positive equity as a gateway error —
never as a drawdown. equity 0.0 reads as 'below the static floor' and would
flatten the whole book on a telemetry glitch."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from guardian.config import AccountConfig, GuardianConfig, TargetConfig
from guardian.gateway import GatewayError
from guardian.loop import run_once
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
            state = run_once(_cfg(tmp), gateway, NoNotify(), NoNews(), GuardianState())
            self.assertEqual(state.equity_now, 50000.0)
            self.assertFalse(gateway.killed)
