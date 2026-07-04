"""M5 flows against a real database: lead-source registry -> on-demand
collect -> leads/scores/events -> detail with decrypted contact ->
re-collect dedup -> anonymization.

Runs with ONLY PostgreSQL available: the collector, embedder, vector index,
storage and LLM are fakes injected through the create_app(kb_adapters=...,
competitor_adapters=..., agent_runtime=...) seams — AgentRuntime.lead_collector
carries the FakeLeadCollector into the customer-discovery agent. Celery
dispatch is forced to fail so :collect exercises the BackgroundTasks
in-process fallback. Requires the orchestrator package on the path
(PYTHONPATH=services/orchestrator/src); skipped cleanly otherwise.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set"),
]

pytest.importorskip("orchestrator")

from src.application.lead_discovery import CollectedDoc  # noqa: E402
from src.infrastructure.agent_runtime import AgentRuntime  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeAgentLlm,
    FakeChangeAnalyst,
    FakeEmbedder,
    FakeEscalator,
    FakeFetcher,
    FakeLeadCollector,
    InMemoryKeywordIndex,
    InMemoryObjectStorage,
    InMemoryVectorIndex,
    fake_extract,
)

TH_LEAD = (
    "u/somchai_75\nหาวิลล่าที่เกาะสมุย\n\n" "กำลังตามหาวิลล่าแถวสมุยสำหรับ 4 คน เดือนหน้า งบ 30,000 บาทครับ"
)
EN_LEAD = (
    "u/jane_doe\nLooking for a pool villa in Koh Samui\n\n"
    "We are looking for a villa in Koh Samui in August for 2 people, budget $1500."
)
NOISE = "u/bob\nBest ramen in Bangkok\n\nWhere do I find good ramen around Sukhumvit?"


def _async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
def collector() -> FakeLeadCollector:
    return FakeLeadCollector()


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, collector: FakeLeadCollector
) -> AsyncIterator[FastAPI]:
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
            fetcher=FakeFetcher(),
            analyst=FakeChangeAnalyst(None),
        ),
        # No scripted responses: the LLM returns None and classification runs
        # the deterministic §8.3 rules — no network, fully reproducible.
        agent_runtime=AgentRuntime(
            llm=FakeAgentLlm(),
            escalator=FakeEscalator(),
            line_push=None,
            lead_collector=collector,
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


def _docs(marker: str) -> list[CollectedDoc]:
    now = datetime.now(UTC)
    return [
        CollectedDoc(
            url=f"https://www.reddit.com/r/kohsamui/{marker}-th",
            content=TH_LEAD.replace("u/somchai_75", f"u/somchai_{marker}"),
            fetched_at=now,
        ),
        CollectedDoc(
            url=f"https://www.reddit.com/r/kohsamui/{marker}-en",
            content=EN_LEAD.replace("u/jane_doe", f"u/jane_{marker}"),
            fetched_at=now,
        ),
        CollectedDoc(
            url=f"https://www.reddit.com/r/kohsamui/{marker}-noise",
            content=NOISE.replace("u/bob", f"u/bob_{marker}"),
            fetched_at=now,
        ),
    ]


async def _create_rss_source(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/v1/sources",
        json={
            "name": name,
            "type": "rss",
            "url": f"https://{uuid.uuid4().hex[:10]}.example.com/feed.xml",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _collect(client: AsyncClient, source_id: str) -> None:
    response = await client.post(f"/v1/sources/{source_id}:collect")
    assert response.status_code == 202, response.text
    assert response.json()["dispatched"] is False  # broker down -> inline fallback


async def _leads_from(client: AsyncClient, source_name: str, marker: str) -> list[dict]:
    response = await client.get("/v1/leads", params={"q": marker, "limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ------------------------------------------------------------------ registry


async def test_sources_crud_roundtrip(client: AsyncClient) -> None:
    created = await _create_rss_source(client, _unique("Samui blog"))
    assert created["type"] == "rss" and created["enabled"] is True
    assert created["tos_policy"] == "allowed"
    assert created["rate_limit_per_hr"] == 12

    listed = await client.get("/v1/sources")
    assert listed.status_code == 200
    assert any(row["id"] == created["id"] for row in listed.json())

    patched = await client.patch(
        f"/v1/sources/{created['id']}", json={"enabled": False, "rate_limit_per_hr": 6}
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["rate_limit_per_hr"] == 6

    deleted = await client.delete(f"/v1/sources/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.delete(f"/v1/sources/{created['id']}")).status_code == 404


async def test_reddit_source_normalizes_subreddit(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/sources",
        json={
            "name": _unique("r/kohsamui"),
            "type": "reddit",
            "config": {"subreddit": "r/KohSamui/", "query": "villa"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["config"] == {"subreddit": "kohsamui", "query": "villa"}


async def test_facebook_rss_source_refused_422(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/sources",
        json={
            "name": _unique("fb group"),
            "type": "rss",
            "url": "https://www.facebook.com/groups/samui/feed",
        },
    )
    assert response.status_code == 422
    assert "facebook" in response.json()["detail"].lower() or "§8.4" in response.json()["detail"]


async def test_rss_source_without_url_refused_422(client: AsyncClient) -> None:
    response = await client.post("/v1/sources", json={"name": _unique("no url"), "type": "rss"})
    assert response.status_code == 422


async def test_competitor_sources_hidden_from_lead_registry(client: AsyncClient) -> None:
    url = f"https://{uuid.uuid4().hex[:10]}.example.com"
    competitor = await client.post(
        "/v1/competitors",
        json={"name": _unique("Villa Rival"), "sources": [{"type": "website", "url": url}]},
    )
    assert competitor.status_code == 201, competitor.text
    source_id = competitor.json()["sources"][0]["id"]

    listed = (await client.get("/v1/sources")).json()
    assert all(row["id"] != source_id for row in listed)
    assert (await client.delete(f"/v1/sources/{source_id}")).status_code == 404
    assert (await client.post(f"/v1/sources/{source_id}:collect")).status_code == 404


# ------------------------------------------------------------------ pipeline


async def test_collect_creates_leads_scores_events(
    client: AsyncClient, collector: FakeLeadCollector
) -> None:
    marker = uuid.uuid4().hex[:8]
    source = await _create_rss_source(client, _unique("Samui feed"))
    collector.set(uuid.UUID(source["id"]), _docs(marker))

    await _collect(client, source["id"])

    # Source status records the outcome.
    rows = (await client.get("/v1/sources")).json()
    row = next(r for r in rows if r["id"] == source["id"])
    assert row["last_status"] == "ok: 3 docs, 2 leads"
    assert row["last_checked_at"] is not None

    # Two leads (TH + EN), the noise doc produced none.
    leads = await _leads_from(client, source["name"], marker)
    assert len(leads) == 2
    by_name = {lead["name"]: lead for lead in leads}
    assert f"u/somchai_{marker}" in by_name and f"u/jane_{marker}" in by_name
    th = by_name[f"u/somchai_{marker}"]
    assert th["stage"] == "discovered" and th["kind"] == "guest"
    assert th["locale"] == "th" and th["intent_score"] > 0

    # Detail: decrypted contact + newest-first events + rules-v1 score.
    detail = (await client.get(f"/v1/leads/{th['id']}")).json()
    assert detail["contact"] == {
        "platform": "reddit",
        "handle": f"u/somchai_{marker}",
        "url": f"https://www.reddit.com/r/kohsamui/{marker}-th",
    }
    assert detail["score"]["model_version"] == "rules-v1"
    assert detail["score"]["value"] == th["intent_score"]
    assert detail["score"]["features"]["explicit_intent"] == 25
    event_types = [event["type"] for event in detail["events"]]
    assert "discovered" in event_types
    discovered = next(e for e in detail["events"] if e["type"] == "discovered")
    assert discovered["payload"]["url"].endswith(f"{marker}-th")
    assert len(discovered["payload"]["excerpt"]) <= 300


async def test_recollect_no_duplicates_and_reobserved(
    client: AsyncClient, collector: FakeLeadCollector
) -> None:
    marker = uuid.uuid4().hex[:8]
    source = await _create_rss_source(client, _unique("Samui feed"))
    source_id = uuid.UUID(source["id"])
    docs = _docs(marker)
    collector.set(source_id, docs)
    await _collect(client, source["id"])

    # Identical docs again: raw dedup -> nothing new, no reobservations.
    await _collect(client, source["id"])
    leads = await _leads_from(client, source["name"], marker)
    assert len(leads) == 2

    # Same author + normalized-identical text with different raw bytes ->
    # exact lead dedup -> 'reobserved' event, still 2 leads.
    variant = CollectedDoc(
        url=docs[1].url + "-repost",
        content=docs[1].content.lower().replace(" villa ", "  villa "),
        fetched_at=datetime.now(UTC),
    )
    collector.set(source_id, [variant])
    await _collect(client, source["id"])

    leads = await _leads_from(client, source["name"], marker)
    assert len(leads) == 2
    jane = next(lead for lead in leads if lead["name"] == f"u/jane_{marker}")
    detail = (await client.get(f"/v1/leads/{jane['id']}")).json()
    assert [event["type"] for event in detail["events"]].count("reobserved") == 1
    assert detail["events"][0]["type"] == "reobserved"  # newest first


async def test_leads_kind_filter(client: AsyncClient, collector: FakeLeadCollector) -> None:
    marker = uuid.uuid4().hex[:8]
    source = await _create_rss_source(client, _unique("Samui feed"))
    b2b_doc = CollectedDoc(
        url=f"https://www.reddit.com/r/kohsamui/{marker}-b2b",
        content=(
            f"u/retreat_{marker}\nRetreat venue Koh Samui\n\n"
            "Organizing a yoga retreat on koh samui for 20 people in November."
        ),
        fetched_at=datetime.now(UTC),
    )
    collector.set(uuid.UUID(source["id"]), [*_docs(marker), b2b_doc])
    await _collect(client, source["id"])

    all_leads = await _leads_from(client, source["name"], marker)
    assert len(all_leads) == 3

    response = await client.get("/v1/leads", params={"q": marker, "kind": "b2b"})
    b2b = response.json()["items"]
    assert [lead["name"] for lead in b2b] == [f"u/retreat_{marker}"]

    guests = (await client.get("/v1/leads", params={"q": marker, "kind": "guest"})).json()["items"]
    assert len(guests) == 2

    bad = await client.get("/v1/leads", params={"kind": "aliens"})
    assert bad.status_code == 422  # Literal-validated query param


async def test_skipped_status_when_collector_unconfigured(
    client: AsyncClient, collector: FakeLeadCollector
) -> None:
    response = await client.post(
        "/v1/sources",
        json={
            "name": _unique("r/kohsamui"),
            "type": "reddit",
            "config": {"subreddit": "kohsamui"},
        },
    )
    assert response.status_code == 201
    source = response.json()
    collector.not_configured.add(uuid.UUID(source["id"]))

    await _collect(client, source["id"])

    rows = (await client.get("/v1/sources")).json()
    row = next(r for r in rows if r["id"] == source["id"])
    assert row["last_status"] == "skipped: no credentials"


# -------------------------------------------------------------- anonymization


async def test_anonymization_flow(app: FastAPI, client: AsyncClient) -> None:
    from src.application.lead_maintenance import (
        ANONYMIZED_NAME,
        LeadMaintenanceUseCases,
    )
    from src.infrastructure.audit import SqlAuditWriter
    from src.infrastructure.models import Lead
    from src.infrastructure.repositories import LeadMaintenanceSqlRepository

    unique = uuid.uuid4().hex
    old = datetime.now(UTC) - timedelta(days=600)
    async with app.state.sessionmaker() as session:
        lead = Lead(
            kind="guest",
            name=f"u/stale_{unique}",
            contact_json={"enc": "legacy-token"},
            intent_score=40,
            stage="discovered",
            dedup_hash=unique,
            first_seen_at=old,
            last_activity_at=old,
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    async with app.state.sessionmaker() as session:
        use_cases = LeadMaintenanceUseCases(
            LeadMaintenanceSqlRepository(session), SqlAuditWriter(session)
        )
        result = await use_cases.anonymize_stale_leads("test")
        await session.commit()
    assert result["anonymized"] >= 1

    detail = (await client.get(f"/v1/leads/{lead_id}")).json()
    assert detail["name"] == ANONYMIZED_NAME
    assert detail["contact"] is None
    assert "anonymized" in [event["type"] for event in detail["events"]]
