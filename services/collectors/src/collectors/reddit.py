"""Reddit collector — official API only (§8.4: ✅ allowed within API terms).

App-only OAuth (client_credentials): read-only access to public subreddit
listings, which is all lead discovery needs. The User-Agent follows Reddit's
API rules (platform:app-id:version with contact). Without credentials the
collector reports ``is_configured == False`` and callers skip it — never
scrape reddit.com HTML as a fallback.
"""

from __future__ import annotations

import json
import time

import httpx

from collectors.base import RawDocument
from collectors.compliance import ComplianceGate, SourcePolicy

REDDIT_USER_AGENT = "server:aibos-lead-discovery:0.1 (contact ch_company@howtoniksen.com)"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"
_TOKEN_SLACK_S = 60  # refresh this long before actual expiry
_LISTING_LIMIT = 50


class RedditCollector:
    """Collects new posts from one public subreddit (optionally keyword-filtered)."""

    def __init__(
        self,
        gate: ComplianceGate,
        policy: SourcePolicy,
        subreddit: str,
        query: str | None = None,
        *,
        client_id: str = "",
        client_secret: str = "",
        token_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.source_name = policy.name
        self._gate = gate
        self._policy = policy
        self._subreddit = subreddit.removeprefix("r/").strip("/").lower()
        self._query = query
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_client = token_client
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def fetch(self) -> list[RawDocument]:
        if not self.is_configured:
            return []
        token = await self._access_token()
        if self._query:
            url = (
                f"{_API_BASE}/r/{self._subreddit}/search"
                f"?q={httpx.QueryParams({'q': self._query})['q']}"
                f"&restrict_sr=1&sort=new&limit={_LISTING_LIMIT}"
            )
        else:
            url = f"{_API_BASE}/r/{self._subreddit}/new?limit={_LISTING_LIMIT}"
        body = await self._gate.fetch(
            self._policy,
            url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_USER_AGENT},
            check_robots=False,  # official API endpoint: API terms govern, not robots.txt
        )
        return self._parse_listing(body)

    def _parse_listing(self, body: str) -> list[RawDocument]:
        data = json.loads(body)
        docs: list[RawDocument] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = post.get("title") or ""
            selftext = post.get("selftext") or ""
            permalink = post.get("permalink") or ""
            author = post.get("author") or ""
            if not title or not permalink or author in ("[deleted]", ""):
                continue
            docs.append(
                RawDocument(
                    source_name=self.source_name,
                    url=f"https://www.reddit.com{permalink}",
                    # Author handle leads the content so the extractor can pick
                    # it up as the public contact handle (PDPA-minimal, §8.5).
                    content=f"u/{author}\n{title}\n\n{selftext}".strip(),
                )
            )
        return docs

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        client = self._token_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._token_client is None
        try:
            resp = await client.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"User-Agent": REDDIT_USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        finally:
            if owns_client:
                await client.aclose()
        self._token = payload["access_token"]
        self._token_expires_at = (
            time.monotonic() + float(payload.get("expires_in", 3600)) - _TOKEN_SLACK_S
        )
        return self._token
