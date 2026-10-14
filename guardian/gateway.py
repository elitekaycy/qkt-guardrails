"""Thin client for mt5-gateway — the only system the guardian ever talks to."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def _send(self, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._base_url + path, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise GatewayError(f"{method} {path} failed: {e}") from e

    def _request(self, path: str, method: str = "GET") -> dict[str, object]:
        parsed = self._send(path, method)
        if not isinstance(parsed, dict):
            raise GatewayError(f"{method} {path}: expected a JSON object, got {type(parsed).__name__}")
        return parsed

    def account(self) -> dict[str, object]:
        raw = self._request("/account")
        data = raw.get("data")
        return data if isinstance(data, dict) else raw

    def health(self) -> dict[str, object]:
        return self._request("/health")

    def kill_switch_active(self) -> bool:
        return bool(self.health().get("kill_switch_active"))

    def kill(self, flatten: bool) -> None:
        path = "/kill?flatten=true" if flatten else "/kill"
        self._request(path, "POST")

    def positions(self) -> list[dict[str, Any]]:
        """Open positions. Gateways differ: older builds return a bare array, newer ones
        wrap it as {"data": [...]}; accept both and treat anything else as an error rather
        than as an empty book, because "no positions" is exactly the answer that would make
        a weekend flatten silently do nothing."""
        parsed = self._send("/get_positions")
        if isinstance(parsed, dict):
            parsed = parsed.get("data")
        if not isinstance(parsed, list):
            raise GatewayError(f"GET /get_positions: expected a JSON array, got {type(parsed).__name__}")
        return [p for p in parsed if isinstance(p, dict)]

    def close_position(self, position: dict[str, Any]) -> None:
        """Close one open position. The gateway wants the whole record it handed us back,
        not just the ticket."""
        self._send("/close_position", "POST", {"position": position})

    def flatten_except(self, spare_symbols: tuple[str, ...]) -> list[str]:
        """Close every open position whose symbol is not spared. Returns the symbols closed.

        This is the guardian's own selective flatten: the gateway's /kill?flatten=true is
        all-or-nothing and also engages the account-global switch, which would stop the very
        symbols we are sparing. Both calls used here are plain position endpoints, so the
        switch must be OFF -- the WEEKEND-PARTIAL rung guarantees that by never engaging it.
        """
        spared = {s.upper() for s in spare_symbols}
        closed: list[str] = []
        for position in self.positions():
            symbol = str(position.get("symbol", "")).upper()
            if not symbol:
                raise GatewayError(f"position without a symbol: {position!r}")
            if symbol in spared:
                continue
            self.close_position(position)
            closed.append(symbol)
        return closed

    def release(self) -> None:
        self._request("/kill/release", "POST")
