"""The guardian's own selective flatten, and the loop branch that drives it.

`flatten_except` replaces the gateway's all-or-nothing /kill?flatten=true for the weekend
rung. It must close exactly the unspared symbols, must refuse to treat a malformed payload
as an empty book, and must never run while the kill switch is on -- the position endpoints
it uses are kill-gated, so a close would 423 and the book would silently stay open.
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

from guardian.config import AccountConfig, GuardianConfig, LadderConfig, TargetConfig
from guardian.gateway import GatewayClient, GatewayError
from guardian.loop import run_once
from guardian.state import GuardianState

BOOK = [
    {"ticket": 1, "symbol": "XAUUSD", "volume": 0.01},
    {"ticket": 2, "symbol": "BTCUSD", "volume": 0.01},
    {"ticket": 3, "symbol": "EURUSD", "volume": 0.04},
]


class _Handler(http.server.BaseHTTPRequestHandler):
    positions_body: object = {"data": list(BOOK)}
    closed: list[int] = []

    def _respond(self, body: object, code: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/get_positions":
            self._respond(_Handler.positions_body)
        elif self.path == "/health":
            self._respond({"kill_switch_active": False})
        elif self.path == "/account":
            self._respond({"data": {"equity": 50000.0}})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/close_position":
            _Handler.closed.append(body["position"]["ticket"])
        self._respond({"ok": True})

    def log_message(self, *args: object) -> None:
        pass


class SelectiveFlattenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _Handler.positions_body = {"data": list(BOOK)}
        _Handler.closed = []

    def client(self) -> GatewayClient:
        return GatewayClient(self.url, "k")

    def test_spares_the_named_symbol_and_closes_the_rest(self) -> None:
        closed = self.client().flatten_except(("BTCUSD",))
        self.assertEqual(sorted(closed), ["EURUSD", "XAUUSD"])
        self.assertEqual(sorted(_Handler.closed), [1, 3])

    def test_empty_spare_list_closes_everything(self) -> None:
        closed = self.client().flatten_except(())
        self.assertEqual(len(closed), 3)
        self.assertEqual(sorted(_Handler.closed), [1, 2, 3])

    def test_spare_matching_is_case_insensitive(self) -> None:
        self.client().flatten_except(("btcusd",))
        self.assertNotIn(2, _Handler.closed)

    def test_bare_array_payload_is_accepted(self) -> None:
        _Handler.positions_body = list(BOOK)
        closed = self.client().flatten_except(("BTCUSD",))
        self.assertEqual(sorted(closed), ["EURUSD", "XAUUSD"])

    def test_malformed_payload_raises_rather_than_reading_as_empty(self) -> None:
        _Handler.positions_body = {"data": "not-a-list"}
        with self.assertRaises(GatewayError):
            self.client().flatten_except(("BTCUSD",))
        self.assertEqual(_Handler.closed, [])

    def test_position_without_a_symbol_raises(self) -> None:
        _Handler.positions_body = {"data": [{"ticket": 9, "volume": 0.01}]}
        with self.assertRaises(GatewayError):
            self.client().flatten_except(("BTCUSD",))


class WeekendPartialLoopTest(unittest.TestCase):
    """run_once on the WEEKEND-PARTIAL rung: close the weekday book, spare crypto,
    and leave the account-global switch alone."""

    def setUp(self) -> None:
        _Handler.positions_body = {"data": list(BOOK)}
        _Handler.closed = []
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loop_closes_weekday_book_and_never_kills(self) -> None:
        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        killed: list[bool] = []

        class Gateway(GatewayClient):
            def kill(self, flatten: bool) -> None:
                killed.append(flatten)

        cfg = GuardianConfig(
            target=TargetConfig(name="t", gateway_url="x", api_key="k"),
            account=AccountConfig(initial_balance=50000.0),
            ladder=LadderConfig(weekend_exclude="BTCUSD"),
            state_path=str(Path(self.tmp.name) / "state.json"),
        )
        gateway = Gateway(f"http://127.0.0.1:{server.server_port}", "k")
        state = GuardianState(day="2026-09-04", prev_close=50000.0, equity_now=50000.0)

        class NoNews:
            def windows(self) -> tuple[()]:
                return ()

        class NoNotify:
            def send(self, _message: str) -> None:
                pass

        run_once(
            cfg, gateway, NoNotify(), NoNews(), state,
            now=dt.datetime(2026, 9, 4, 21, 30, tzinfo=dt.UTC),
        )
        server.shutdown()
        server.server_close()

        self.assertEqual(killed, [], "WEEKEND-PARTIAL must not engage the kill switch")
        self.assertEqual(sorted(_Handler.closed), [1, 3], "crypto ticket 2 must stay open")


if __name__ == "__main__":
    unittest.main()
