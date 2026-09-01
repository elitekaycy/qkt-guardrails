import http.server
import json
import threading
import unittest

from guardian.gateway import GatewayClient, GatewayError


class _FakeGateway(http.server.BaseHTTPRequestHandler):
    calls: list[tuple[str, str, str]] = []  # (method, path, auth header)

    def _respond(self, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        _FakeGateway.calls.append(("GET", self.path, self.headers.get("Authorization", "")))
        if self.path == "/account":
            self._respond({"data": {"equity": 9950.5, "balance": 10000}})
        elif self.path == "/health":
            self._respond({"kill_switch_active": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        _FakeGateway.calls.append(("POST", self.path, self.headers.get("Authorization", "")))
        self._respond({"ok": True})

    def log_message(self, *args: object) -> None:
        pass


class GatewayClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _FakeGateway)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join()

    def setUp(self) -> None:
        _FakeGateway.calls.clear()
        self.client = GatewayClient(f"http://127.0.0.1:{self.port}", api_key="test-key")

    def test_account_unwraps_the_data_envelope(self) -> None:
        account = self.client.account()
        self.assertEqual(account["equity"], 9950.5)

    def test_requests_carry_bearer_auth(self) -> None:
        self.client.account()
        _, _, auth = _FakeGateway.calls[0]
        self.assertEqual(auth, "Bearer test-key")

    def test_kill_switch_active_reads_health(self) -> None:
        self.assertTrue(self.client.kill_switch_active())

    def test_kill_with_flatten_hits_the_flatten_query_param(self) -> None:
        self.client.kill(flatten=True)
        method, path, _ = _FakeGateway.calls[0]
        self.assertEqual((method, path), ("POST", "/kill?flatten=true"))

    def test_kill_without_flatten_hits_plain_kill(self) -> None:
        self.client.kill(flatten=False)
        method, path, _ = _FakeGateway.calls[0]
        self.assertEqual((method, path), ("POST", "/kill"))

    def test_unreachable_host_raises_gateway_error(self) -> None:
        client = GatewayClient("http://127.0.0.1:1", api_key="k", timeout_seconds=1)
        with self.assertRaises(GatewayError):
            client.account()


if __name__ == "__main__":
    unittest.main()
