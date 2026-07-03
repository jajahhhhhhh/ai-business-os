"""M3 flows against a real database: competitor registry -> sweep -> feed ->
weekly report.

These tests run with ONLY PostgreSQL available: the compliance-gated fetcher,
object storage and the Anthropic analyst are replaced with the in-memory
fakes from tests/fakes.py, injected through the
create_app(competitor_adapters=...) seam (a module-local `app` fixture
shadows the conftest one). Celery dispatch is forced to fail so :check
exercises the BackgroundTasks in-process fallback."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.fakes import (
    UPGRADE_ANALYSIS_HEADER,
    FakeChangeAnalyst,
    FakeEmbedder,
    FakeFetcher,
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

HTML_V1 = "<h1>Sunset Villa</h1><p>Pool villa in Lipa Noi</p>"
HTML_V2 = "<h1>Sunset Villa</h1><p>Pool villa in Lipa Noi</p><p>ราคาใหม่ 4,900 บาท</p>"


def _async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
def fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
async def app(monkeypatch: pytest.MonkeyPatch, fetcher: FakeFetcher) -> AsyncIterator[FastAPI]:
    from src import worker
    from src.config import Settings
    from src.infrastructure.adapters import CompetitorAdapters, KbAdapters
    from src.infrastructure.models import Base
    from src.main import create_app

    def _broker_down(*args: object, **kwargs: object) -> None:
        raise ConnectionError("broker unreachable (forced by test)")

    monkeypatch.setattr(worker.celery_app, "send_task", _broker_down)

    settings = Settings(database_url=_async_url(DATABASE_URL), env="dev")
    application = create_app(
        settings,
        kb_adapters=KbAdapters(
            storage=InMemoryObjectStorage(),
            keyword_index=InMemoryKeywordIndex(),
            vector_index=InMemoryVectorIndex(),
            embedder=FakeEmbedder(available=True),
            extract=fake_extract,
        ),
        competitor_adapters=CompetitorAdapters(
            storage=InMemoryObjectStorage(),
            fetcher=fetcher,
            analyst=FakeChangeAnalyst(None),  # classify falls back to the rules
        ),
    )

    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


def _unique(name: str) -> str:
    return f"{name} {uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, fetcher: FakeFetcher, url: str) -> dict:
    fetcher.set(url, HTML_V1)
    response = await client.post(
        "/v1/competitors",
        json={
            "name": _unique("Sunset Villa"),
            "kind": "villa",
            "website": url,
            "sources": [{"type": "website", "url": url}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_register_with_sources_and_list(client: AsyncClient, fetcher: FakeFetcher) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    created = await _register(client, fetcher, url)

    [source] = created["sources"]
    assert source["type"] == "website"
    assert source["url"] == url
    assert source["tos_policy"] == "allowed"
    assert source["enabled"] is True
    assert source["last_checked_at"] is None and source["last_status"] is None

    listed = await client.get("/v1/competitors")
    assert listed.status_code == 200
    match = next(c for c in listed.json() if c["id"] == created["id"])
    assert [s["id"] for s in match["sources"]] == [source["id"]]


async def test_facebook_source_is_refused_422(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/competitors",
        json={
            "name": _unique("Copycat"),
            "sources": [{"type": "website", "url": "https://www.facebook.com/copycat"}],
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert "§8.4" in body["detail"]  # Thai-readable source-policy refusal
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_check_sweep_baseline_then_change_event_in_global_feed(
    client: AsyncClient, fetcher: FakeFetcher
) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    created = await _register(client, fetcher, url)
    competitor_id = created["id"]

    # v1 -> baseline: snapshot stored, NO change event.
    accepted = await client.post(f"/v1/competitors/{competitor_id}:check")
    assert accepted.status_code == 202
    assert accepted.json()["dispatched"] is False  # broker down -> inline fallback

    detail = await client.get(f"/v1/competitors/{competitor_id}")
    [source] = detail.json()["sources"]
    assert source["last_status"] == "baseline"
    assert source["last_checked_at"] is not None

    changes = await client.get(f"/v1/competitors/{competitor_id}/changes")
    assert changes.json() == []

    # v2 -> changed: pricing event appears in the global feed with the name.
    fetcher.set(url, HTML_V2)
    assert (await client.post(f"/v1/competitors/{competitor_id}:check")).status_code == 202

    feed = await client.get("/v1/competitors/changes", params={"limit": 50})
    assert feed.status_code == 200
    event = next(e for e in feed.json() if e["competitor_id"] == competitor_id)
    assert event["competitor_name"] == created["name"]
    assert event["category"] == "pricing" and event["severity"] == "high"
    assert "ราคาใหม่ 4,900 บาท" in event["summary"]

    detail = await client.get(f"/v1/competitors/{competitor_id}")
    assert detail.json()["sources"][0]["last_status"] == "changed"

    # Severity filter excludes it.
    low_only = await client.get("/v1/competitors/changes", params={"severity": "low"})
    assert all(e["competitor_id"] != competitor_id for e in low_only.json())


async def test_weekly_report_generates_thai_body(client: AsyncClient, fetcher: FakeFetcher) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    created = await _register(client, fetcher, url)
    await client.post(f"/v1/competitors/{created['id']}:check")
    fetcher.set(url, HTML_V2)
    await client.post(f"/v1/competitors/{created['id']}:check")

    response = await client.post("/v1/reports/weekly-competitor:generate")
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["kind"] == "weekly" and report["lang"] == "th"
    assert report["period"].count("-W") == 1  # e.g. 2026-W27
    assert "รายงานคู่แข่งประจำสัปดาห์" in report["body"]
    assert created["name"] in report["body"]
    # FakeChangeAnalyst upgrades the draft like the real analyst is prompted to.
    assert UPGRADE_ANALYSIS_HEADER in report["body"]

    listed = await client.get("/v1/reports", params={"kind": "weekly"})
    assert any(r["id"] == report["id"] for r in listed.json())


async def test_deactivated_competitor_is_skipped_by_sweep(
    client: AsyncClient, fetcher: FakeFetcher
) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    created = await _register(client, fetcher, url)
    competitor_id = created["id"]

    patched = await client.patch(f"/v1/competitors/{competitor_id}", json={"active": False})
    assert patched.status_code == 200 and patched.json()["active"] is False

    before = len(fetcher.calls)
    assert (await client.post(f"/v1/competitors/{competitor_id}:check")).status_code == 202
    assert len(fetcher.calls) == before  # nothing fetched

    detail = await client.get(f"/v1/competitors/{competitor_id}")
    assert detail.json()["sources"][0]["last_status"] is None  # untouched


async def test_source_add_and_delete(client: AsyncClient, fetcher: FakeFetcher) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    created = await _register(client, fetcher, url)
    competitor_id = created["id"]

    added = await client.post(
        f"/v1/competitors/{competitor_id}/sources",
        json={"type": "rss", "url": f"{url}/feed.xml"},
    )
    assert added.status_code == 201
    source_id = added.json()["id"]

    refused = await client.post(
        f"/v1/competitors/{competitor_id}/sources",
        json={"type": "rss", "url": "https://agoda.com/feed"},
    )
    assert refused.status_code == 422

    deleted = await client.delete(f"/v1/competitors/{competitor_id}/sources/{source_id}")
    assert deleted.status_code == 204

    detail = await client.get(f"/v1/competitors/{competitor_id}")
    assert all(s["id"] != source_id for s in detail.json()["sources"])
