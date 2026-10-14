"""A stand-in for mt5-gateway, to try the guardian with no broker.

    python3 examples/fake-gateway.py configs/equity.txt

Serves the calls the guardian makes on 127.0.0.1:5811 (token `demo-token`).
Equity is whatever number is in the file, read on every call: change the file to
move the account. Every POST (/kill, /kill?flatten=true, /kill/release) is printed.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOKEN = "demo-token"
PORT = 5811
EQUITY_FILE = Path(sys.argv[1] if len(sys.argv) > 1 else "equity.txt")
kill_switch = False


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _allowed(self) -> bool:
        if self.path == "/calendar":  # the news feed is public
            return True
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._reply(401, {"error": "bad token"})
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed():
            return
        if self.path == "/calendar":
            self._reply(200, [])
        elif self.path == "/account":
            self._reply(200, {"data": {"equity": float(EQUITY_FILE.read_text())}})
        elif self.path == "/health":
            self._reply(200, {"status": "ok", "kill_switch_active": kill_switch})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        global kill_switch
        if not self._allowed():
            return
        if self.path.startswith("/kill/release"):
            kill_switch = False
        elif self.path.startswith("/kill"):
            kill_switch = True
        else:
            self._reply(404, {"error": "not found"})
            return
        print(f"POST {self.path}  kill_switch_active={kill_switch}", flush=True)
        self._reply(200, {"ok": True, "kill_switch_active": kill_switch})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
