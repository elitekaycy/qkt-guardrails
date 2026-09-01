"""run_once must treat a payload without positive equity as a gateway error —
never as a drawdown. equity 0.0 reads as 'below the static floor' and would
flatten the whole book on a telemetry glitch."""
from __future__ import annotations

import pytest

from guardian.config import AccountConfig, GuardianConfig, TargetConfig
from guardian.gateway import GatewayError
from guardian.loop import run_once
from guardian.state import GuardianState


class FakeGateway:
    def __init__(self, account_payload):
        self._account = account_payload
        self.killed = False
        self.flattened = False

    def account(self):
        return self._account

    def kill_switch_active(self):
        return False

    def kill(self, flatten):
        self.killed = True
        self.flattened = flatten

    def release(self):
        pass


class NoNews:
    def events(self):
        return []


class NoNotify:
    def send(self, _):
        pass


@pytest.fixture
def cfg(tmp_path):
    return GuardianConfig(
        target=TargetConfig(name="t", gateway_url="http://x", api_key="k"),
        account=AccountConfig(initial_balance=50000),
        state_path=str(tmp_path / "state.json"),
    )


BAD_PAYLOADS = [{}, {"equity": None}, {"equity": 0}, {"equity": 0.0}, {"equity": "nan-ish"}, {"equity": -5}]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_bad_equity_is_a_gateway_error_not_a_flatten(cfg, payload):
    gw = FakeGateway(payload)
    with pytest.raises(GatewayError):
        run_once(cfg, gw, NoNotify(), NoNews(), GuardianState())
    assert gw.killed is False, "must never touch the kill switch on bad data"


def test_valid_equity_still_evaluates(cfg):
    gw = FakeGateway({"equity": 50000.0})
    state = run_once(cfg, gw, NoNotify(), NoNews(), GuardianState())
    assert state.equity_now == 50000.0
    assert gw.killed is False
