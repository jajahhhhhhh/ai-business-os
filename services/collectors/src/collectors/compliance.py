"""The compliance gate: every outbound fetch must pass through here.

Enforces, in order (§8.4 of the architecture):
1. ToS policy — the source's registered policy must be ``allowed``. Domains on the
   hard blocklist (Facebook, OTA platforms) are refused even if a source row says
   otherwise: the check is structural, not conventional.
2. robots.txt — fetched once per host, cached, evaluated for our honest User-Agent.
3. Rate limit — token bucket per source (in-memory; the Celery deployment swaps in
   a Redis-backed limiter with the same interface).

Violations raise :class:`ComplianceViolation` and are expected to be logged and
counted — never silently retried around.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse

import httpx

USER_AGENT = "aibos-collector/0.1 (+https://howtoniksen.com/bot; contact ch_company@howtoniksen.com)"

#: Domains that are never fetched regardless of source registry contents.
#: Suffix match against the registrable host (subdomains included).
HARD_BLOCKLIST: frozenset[str] = frozenset(
    {
        "facebook.com",
        "fb.com",
        "instagram.com",
        "airbnb.com",
        "airbnb.co.th",
        "booking.com",
        "agoda.com",
    }
)


class TosPolicy(StrEnum):
    ALLOWED = "allowed"
    REVIEW = "review"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """Registry entry for one source (mirrors the ``sources`` table)."""

    name: str
    tos_policy: TosPolicy
    rate_limit_per_hr: int = 60
    enabled: bool = True


class ComplianceViolation(Exception):
    """A fetch was refused. ``reason`` is machine-readable for metrics."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}")


class RateLimiter(Protocol):
    def acquire(self, key: str, per_hour: int) -> bool: ...


class InMemoryRateLimiter:
    """Token-bucket limiter; adequate for a single worker process."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def acquire(self, key: str, per_hour: int) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(per_hour), now))
        tokens = min(float(per_hour), tokens + (now - last) * per_hour / 3600.0)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


def _host_blocked(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in HARD_BLOCKLIST)


class ComplianceGate:
    """Constructs gated fetch callables for collectors.

    Usage::

        gate = ComplianceGate()
        text = await gate.fetch(policy, "https://example.com/feed.xml")
    """

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        client: httpx.AsyncClient | None = None,
        robots_ttl_s: int = 3600,
    ) -> None:
        self._limiter = rate_limiter or InMemoryRateLimiter()
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        self._robots_ttl_s = robots_ttl_s
        self._robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}

    def check_url(self, policy: SourcePolicy, url: str) -> None:
        """Synchronous checks (blocklist + registry). Raises on violation."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ComplianceViolation("invalid_url", url)
        if _host_blocked(parsed.hostname):
            raise ComplianceViolation("hard_blocklist", parsed.hostname)
        if not policy.enabled:
            raise ComplianceViolation("source_disabled", policy.name)
        if policy.tos_policy is not TosPolicy.ALLOWED:
            raise ComplianceViolation("tos_policy", f"{policy.name} is {policy.tos_policy}")

    async def fetch(self, policy: SourcePolicy, url: str) -> str:
        """Fetch ``url`` if and only if every compliance check passes."""
        self.check_url(policy, url)
        if not self._limiter.acquire(policy.name, policy.rate_limit_per_hr):
            raise ComplianceViolation("rate_limited", policy.name)
        if not await self._robots_allows(url):
            raise ComplianceViolation("robots_txt", url)
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.text

    async def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        now = time.monotonic()
        cached = self._robots_cache.get(origin)
        if cached is None or now - cached[0] > self._robots_ttl_s:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = await self._client.get(f"{origin}/robots.txt")
                if resp.status_code >= 400:
                    # No robots.txt (or server error hiding it): default-allow per RFC 9309,
                    # the per-source rate limit still applies.
                    rp.parse([])
                else:
                    rp.parse(resp.text.splitlines())
            except httpx.HTTPError:
                # Unreachable robots.txt on a reachable-looking host: fail closed.
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots_cache[origin] = (now, rp)
            cached = self._robots_cache[origin]
        return cached[1].can_fetch(USER_AGENT, url)

    async def aclose(self) -> None:
        await self._client.aclose()
