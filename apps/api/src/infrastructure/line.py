"""LINE Messaging API client (push messages to the owner).

Delivery is best-effort by contract: failures are logged and reported as a
boolean; nothing propagates to callers. A missed LINE message must never
fail a report or an API request.
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger("infrastructure.line")

_PUSH_URL = "https://api.line.me/v2/bot/message/push"
_TIMEOUT_SECONDS = 10.0


class LineClient:
    def __init__(self, channel_access_token: str, owner_user_id: str) -> None:
        self._token = channel_access_token
        self._owner_user_id = owner_user_id

    @property
    def is_configured(self) -> bool:
        return bool(self._token and self._owner_user_id)

    async def push_text(self, text: str) -> bool:
        """Push a text message to the owner; returns True on success."""
        if not self.is_configured:
            logger.info("line_push_skipped", reason="not configured")
            return False
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _PUSH_URL,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "to": self._owner_user_id,
                        "messages": [{"type": "text", "text": text[:5000]}],
                    },
                )
            if response.status_code == 200:
                return True
            logger.warning(
                "line_push_failed",
                status_code=response.status_code,
                body=response.text[:500],
            )
            return False
        except Exception as exc:  # noqa: BLE001 - delivery is best-effort by contract
            logger.warning("line_push_error", error=str(exc))
            return False
