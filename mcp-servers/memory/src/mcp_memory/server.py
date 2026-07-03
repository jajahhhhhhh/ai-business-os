"""memory MCP server — thin proxy over /v1/memory (§6, §10).

Env: AIBOS_API_URL (default http://localhost:8000), AIBOS_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("AIBOS_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("AIBOS_API_KEY", "")

VALID_KINDS = ("business", "person", "competitor", "campaign", "decision", "task")

mcp = FastMCP("aibos-memory")


def _client() -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    return httpx.AsyncClient(base_url=API_URL, headers=headers, timeout=30.0)


@mcp.tool()
async def remember(
    kind: str,
    subject: str,
    body: str,
    importance: int = 3,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Store a long-term memory.

    kind: business|person|competitor|campaign|decision|task.
    importance: 1 (trivia) … 5 (critical); low-importance memories decay first
    at consolidation. expires_at: optional ISO-8601 datetime for facts with a
    natural shelf life.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}")
    payload: dict[str, Any] = {
        "kind": kind,
        "subject": subject,
        "body": body,
        "importance": importance,
    }
    if expires_at:
        payload["expires_at"] = expires_at
    async with _client() as client:
        resp = await client.post("/v1/memory", json=payload)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def recall(query: str, kind: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """Recall memories relevant to a query (semantic + keyword, RRF-fused).

    Expired and consolidated-away memories are never returned.
    """
    params: dict[str, Any] = {"q": query, "limit": limit}
    if kind:
        params["kind"] = kind
    async with _client() as client:
        resp = await client.get("/v1/memory/search", params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def consolidate() -> dict[str, Any]:
    """Merge near-duplicate memories and expire stale ones.

    Also runs automatically every Sunday 03:00 Asia/Bangkok; call manually
    after bulk imports. Returns {merged, expired} counts.
    """
    async with _client() as client:
        resp = await client.post("/v1/memory:consolidate")
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
