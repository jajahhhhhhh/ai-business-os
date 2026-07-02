"""Gmail REST client over httpx (no Google SDK): bank-alert e-mail polling.

Auth is the OAuth2 refresh-token flow: a long-lived refresh token (obtained
once, out of band) is exchanged for short-lived access tokens per run. When
credentials are not configured, `is_configured` is False and callers skip.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

logger = structlog.get_logger("infrastructure.gmail")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_TIMEOUT_SECONDS = 20.0

# Known Thai bank alert sender domains; only recent mail is worth polling.
DEFAULT_QUERY = (
    "from:(kasikornbank.com OR scb.co.th OR bangkokbank.com "
    "OR krungsri.com OR ktb.co.th) newer_than:3d"
)

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class GmailMessage:
    id: str
    body_text: str


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    return " ".join(_TAG_RE.sub(" ", html).split())


def _extract_body(payload: dict[str, Any]) -> str:
    """Depth-first extraction: prefer text/plain, fall back to stripped HTML."""
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html = _find_part(payload, "text/html")
    if html:
        return _strip_html(html)
    return ""


def _find_part(part: dict[str, Any], mime: str) -> str | None:
    if part.get("mimeType", "").startswith(mime):
        data = part.get("body", {}).get("data")
        if data:
            return _decode_base64url(data)
    for child in part.get("parts", ()) or ():
        found = _find_part(child, mime)
        if found:
            return found
    return None


class GmailClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._refresh_token)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            _TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        token: str = response.json()["access_token"]
        return token

    async def fetch_messages(
        self, q: str = DEFAULT_QUERY, max_results: int = 50
    ) -> list[GmailMessage]:
        """List messages matching `q` and return their extracted text bodies."""
        if not self.is_configured:
            logger.info("gmail_fetch_skipped", reason="not configured")
            return []
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            headers = {"Authorization": f"Bearer {await self._access_token(client)}"}

            listing = await client.get(
                f"{_API_BASE}/messages",
                params={"q": q, "maxResults": max_results},
                headers=headers,
            )
            listing.raise_for_status()
            refs = listing.json().get("messages", []) or []

            messages: list[GmailMessage] = []
            for ref in refs:
                detail = await client.get(
                    f"{_API_BASE}/messages/{ref['id']}",
                    params={"format": "full"},
                    headers=headers,
                )
                detail.raise_for_status()
                payload = detail.json().get("payload", {})
                body = _extract_body(payload)
                if body:
                    messages.append(GmailMessage(id=ref["id"], body_text=body))
            return messages
