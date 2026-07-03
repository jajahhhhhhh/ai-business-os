"""M2 flows against a real database: KB upload -> index -> search, memory CRUD.

These tests run with ONLY PostgreSQL available: MinIO/Meilisearch/Qdrant are
replaced with the in-memory fakes from tests/fakes.py, injected through the
create_app(kb_adapters=...) seam (a module-local `app` fixture shadows the
conftest one). The real adapters are exercised on the VPS/CI compose stack.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.fakes import (
    FakeEmbedder,
    InMemoryKeywordIndex,
    InMemoryObjectStorage,
    InMemoryVectorIndex,
    fake_extract,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set"),
]

THAI_QUOTE = (
    "ใบเสนอราคางานรีโนเวทวิลล่า ลิปะน้อย เกาะสมุย\n\n"
    "งานไฟฟ้าทั้งหมดรวมค่าแรงและอุปกรณ์ จำนวนเงิน 450,000 บาท\n"
    "งานประปารวมสุขภัณฑ์ 320,000 บาท\n\n"
    "Electrical and plumbing quotation, Lipa Noi villa renovation."
)


def _async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
async def app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """App wired with in-memory KB fakes; Celery dispatch forced to fail so
    uploads exercise the BackgroundTasks in-process fallback (a live local
    Redis would otherwise swallow the task with no worker to run it)."""
    from src import worker
    from src.config import Settings
    from src.infrastructure.adapters import KbAdapters
    from src.infrastructure.models import Base
    from src.main import create_app

    def _broker_down(*args: object, **kwargs: object) -> None:
        raise ConnectionError("broker unreachable (forced by test)")

    monkeypatch.setattr(worker.celery_app, "send_task", _broker_down)

    adapters = KbAdapters(
        storage=InMemoryObjectStorage(),
        keyword_index=InMemoryKeywordIndex(),
        vector_index=InMemoryVectorIndex(),
        embedder=FakeEmbedder(available=True),
        extract=fake_extract,
    )
    settings = Settings(database_url=_async_url(DATABASE_URL), env="dev")
    application = create_app(settings, kb_adapters=adapters)

    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


async def _wait_for_status(
    client: AsyncClient, document_id: str, expected: str, attempts: int = 20
) -> dict:
    """Poll the document until it reaches `expected` status.

    The BackgroundTasks fallback completes within the upload request's ASGI
    call, so the very first poll normally already sees the final status.
    """
    import asyncio

    for _ in range(attempts):
        response = await client.get(f"/v1/kb/documents/{document_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] == expected:
            return body
        assert body["status"] != "failed", body["error"]
        await asyncio.sleep(0.1)
    raise AssertionError(f"document never reached status {expected!r}: {body}")


async def test_kb_upload_index_search_flow(client: AsyncClient) -> None:
    marker = uuid.uuid4().hex[:8]
    title = f"quotation-lipa-noi-{marker}"
    upload = await client.post(
        "/v1/kb/documents",
        files={"file": (f"{title}.txt", THAI_QUOTE.encode("utf-8"), "text/plain")},
        data={"title": title, "lang": "th"},
    )
    assert upload.status_code == 202
    document = upload.json()
    assert document["title"] == title
    assert document["source"] == "upload"
    assert document["size_bytes"] == len(THAI_QUOTE.encode("utf-8"))

    detail = await _wait_for_status(client, document["id"], "indexed")
    assert detail["meili_indexed"] is True
    assert detail["embedded"] is True  # FakeEmbedder is available
    assert detail["chunk_count"] >= 1

    # Listing: newest-first, filterable by status.
    listing = await client.get("/v1/kb/documents", params={"status": "indexed"})
    assert listing.status_code == 200
    assert any(item["id"] == document["id"] for item in listing.json())

    # Thai hybrid search finds the quotation (M2 exit criterion).
    search = await client.get(
        "/v1/kb/search", params={"q": "ใบเสนอราคางานไฟฟ้า", "mode": "hybrid", "limit": 10}
    )
    assert search.status_code == 200
    body = search.json()
    assert body["mode"] == "hybrid"
    assert body["degraded"] is False
    hits = [result for result in body["results"] if result["document_id"] == document["id"]]
    assert hits, body
    assert "ไฟฟ้า" in hits[0]["text"]
    assert set(hits[0]["matched_by"]) <= {"keyword", "semantic"} and hits[0]["matched_by"]

    # English keyword search also finds it (bilingual corpus).
    search_en = await client.get(
        "/v1/kb/search", params={"q": "plumbing quotation", "mode": "keyword"}
    )
    assert search_en.status_code == 200
    assert any(
        result["document_id"] == document["id"] for result in search_en.json()["results"]
    )


async def test_kb_upload_rejects_oversized_file(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings.kb_max_upload_mb = 1
    try:
        upload = await client.post(
            "/v1/kb/documents",
            files={"file": ("big.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
        )
    finally:
        app.state.settings.kb_max_upload_mb = 25
    assert upload.status_code == 413
    assert upload.headers["content-type"].startswith("application/problem+json")


async def test_kb_unsupported_mime_marks_document_failed(client: AsyncClient) -> None:
    # fake_extract decodes utf-8; invalid bytes fail the pipeline, which must
    # end in status=failed (never a 500, never a stuck 'parsing').
    upload = await client.post(
        "/v1/kb/documents",
        files={"file": ("broken.txt", b"\xff\xfe\xfa", "text/plain")},
    )
    assert upload.status_code == 202
    document_id = upload.json()["id"]
    response = await client.get(f"/v1/kb/documents/{document_id}")
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]


async def test_memory_remember_recall_consolidate_flow(client: AsyncClient) -> None:
    marker = uuid.uuid4().hex[:8]
    subject = f"งวดเบิก MR.HOME {marker}"

    first = await client.post(
        "/v1/memory",
        json={
            "kind": "business",
            "subject": subject,
            "body": "งวดที่ 1 ร้อยละ 30 เมื่อเริ่มงาน",
            "importance": 2,
        },
    )
    assert first.status_code == 201
    second = await client.post(
        "/v1/memory",
        json={
            "kind": "business",
            "subject": subject,
            "body": "งวดที่ 1 ร้อยละ 30 เมื่อเริ่มงาน",
            "importance": 5,
        },
    )
    assert second.status_code == 201
    survivor_id = second.json()["id"]

    recall = await client.get("/v1/memory/search", params={"q": marker, "kind": "business"})
    assert recall.status_code == 200
    recalled_ids = {hit["id"] for hit in recall.json()}
    assert {first.json()["id"], survivor_id} <= recalled_ids
    assert all(hit["score"] > 0 for hit in recall.json())

    consolidate = await client.post("/v1/memory:consolidate")
    assert consolidate.status_code == 202
    result = consolidate.json()
    assert result["merged"] >= 1
    assert result["expired"] >= 0

    # After consolidation only the high-importance duplicate is recalled.
    recall_after = await client.get(
        "/v1/memory/search", params={"q": marker, "kind": "business"}
    )
    ids_after = {hit["id"] for hit in recall_after.json()}
    assert survivor_id in ids_after
    assert first.json()["id"] not in ids_after
