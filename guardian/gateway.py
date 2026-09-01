"""Thin client for mt5-gateway — the only system the guardian ever talks to."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def _request(self, path: str, method: str = "GET") -> dict[str, object]:
        req = urllib.request.Request(
            self._base_url + path,
            method=method,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                parsed = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise GatewayError(f"{method} {path} failed: {e}") from e
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

    def release(self) -> None:
        self._request("/kill/release", "POST")
