"""Best-effort Telegram alerts. A notify failure must never break the guard loop."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from guardian.config import NotifyConfig
from guardian.logging import log


class TelegramNotifier:
    def __init__(self, cfg: NotifyConfig, timeout_seconds: float = 10.0) -> None:
        self._cfg = cfg
        self._timeout = timeout_seconds

    def send(self, text: str) -> None:
        if not self._cfg.enabled:
            return
        try:
            body = json.dumps({"chat_id": self._cfg.telegram_chat, "text": f"[guardian] {text}"}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{self._cfg.telegram_token}/sendMessage",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=self._timeout).read()
        except (urllib.error.URLError, TimeoutError) as e:
            log("telegram error:", e)
