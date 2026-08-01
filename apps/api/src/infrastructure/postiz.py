"""Postiz REST client (M6 publishing) — see ADR-0010 for the §7 deviation.

Creates scheduled posts on a Postiz instance. Payload follows Postiz's
documented public API (`POST /public/v1/posts`); validate against your instance
before the first live run. `build_postiz_publisher` returns None when Postiz is
unconfigured so the worker skips cleanly (Gmail/PMS pattern), never raising.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import httpx
import structlog

from src.config import Settings
from src.domain.bank_alerts import BANGKOK_TZ

logger = structlog.get_logger("infrastructure.postiz")

_HTTP_TIMEOUT = 30.0
_PUBLISH_HOUR = 9  # local (Asia/Bangkok) hour to schedule each post at


class PostizClient:
    def __init__(
        self, api_url: str, api_key: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=_HTTP_TIMEOUT,
            headers={"Authorization": api_key},
        )

    async def create_post(self, *, integration_id: str, caption: str, when: date) -> str:
        scheduled_at = datetime.combine(when, time(_PUBLISH_HOUR, 0), tzinfo=BANGKOK_TZ)
        payload: dict[str, Any] = {
            "type": "scheduled",
            "date": scheduled_at.isoformat(),
            "posts": [
                {
                    "integration": {"id": integration_id},
                    "value": [{"content": caption}],
                }
            ],
        }
        resp = await self._client.post("/public/v1/posts", json=payload)
        resp.raise_for_status()
        return _extract_post_id(resp.json())

    async def aclose(self) -> None:
        await self._client.aclose()


def _extract_post_id(data: Any) -> str:
    """Best-effort id extraction across Postiz response shapes."""
    if isinstance(data, dict):
        for key in ("id", "postId", "_id"):
            if data.get(key):
                return str(data[key])
    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("id"):
        return str(data[0]["id"])
    return ""


def build_postiz_publisher(settings: Settings) -> PostizClient | None:
    """The Postiz client, or None when unconfigured (worker skips cleanly)."""
    if settings.postiz_api_url and settings.postiz_api_key:
        return PostizClient(settings.postiz_api_url, settings.postiz_api_key)
    logger.info("postiz_publisher_unconfigured")
    return None
