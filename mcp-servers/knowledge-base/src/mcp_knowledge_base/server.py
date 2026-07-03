"""knowledge-base MCP server — thin, honest proxy over the core API.

Tools mirror /v1/kb endpoints; no logic lives here (§6: tool logic stays out
of agent code, business logic stays in the API).

Env: AIBOS_API_URL (default http://localhost:8000), AIBOS_API_KEY (required
against a prod API; optional in dev where auth is bypassed).
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("AIBOS_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("AIBOS_API_KEY", "")

mcp = FastMCP("aibos-knowledge-base")


def _client() -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    return httpx.AsyncClient(base_url=API_URL, headers=headers, timeout=60.0)


async def _get(path: str, params: dict[str, Any]) -> Any:
    async with _client() as client:
        resp = await client.get(path, params={k: v for k, v in params.items() if v is not None})
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def search(query: str, mode: str = "hybrid", limit: int = 10) -> dict[str, Any]:
    """Search the business knowledge base (quotations, contracts, documents).

    mode: 'hybrid' (default, keyword + semantic with RRF fusion), 'keyword',
    or 'semantic'. Results carry document_id/title, chunk seq, snippet, score.
    A 'degraded: true' response means the semantic side is unavailable and
    only keyword results are shown.
    """
    return await _get("/v1/kb/search", {"q": query, "mode": mode, "limit": limit})


@mcp.tool()
async def get_document(document_id: str) -> dict[str, Any]:
    """Fetch one document's metadata and ingestion status (incl. chunk_count)."""
    return await _get(f"/v1/kb/documents/{document_id}", {})


@mcp.tool()
async def list_documents(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List recent documents, optionally by status: pending|parsing|indexed|failed."""
    return await _get("/v1/kb/documents", {"status": status, "limit": limit})


@mcp.tool()
async def ingest_document(
    path: str, title: str | None = None, lang: str | None = None
) -> dict[str, Any]:
    """Upload a local file (PDF, image, text — max 25 MB) into the knowledge base.

    lang: 'th' or 'en'; omit for auto-detection. Returns the document row;
    ingestion continues asynchronously — poll get_document until status is
    'indexed' (or 'failed', whose 'error' field says why).
    """
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"No such file: {file_path}")
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    data: dict[str, Any] = {}
    if title:
        data["title"] = title
    if lang:
        data["lang"] = lang
    async with _client() as client:
        resp = await client.post(
            "/v1/kb/documents",
            files={"file": (file_path.name, file_path.read_bytes(), mime)},
            data=data,
        )
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
