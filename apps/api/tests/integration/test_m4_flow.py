"""M4 flows against a real database: agent trigger -> traced run -> report,
costs aggregation, qa evals, planner fallback, escalation/parking.

Runs with ONLY PostgreSQL available: LLM, LINE and escalation are fakes
injected through the create_app(agent_runtime=...) seam; storage/fetcher/
analyst come from the M2/M3 fakes. Celery dispatch is forced to fail so
triggers exercise the BackgroundTasks in-process fallback. Requires the
orchestrator package on the path (PYTHONPATH=services/orchestrator/src);
skipped cleanly otherwise.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set"),
]

pytest.importorskip("orchestrator")

from src.infrastructure.agent_runtime import AgentRuntime, run_agent  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeAgentLlm,
    FakeChangeAnalyst,
    FakeEmbedder,
    FakeEscalator,
    FakeFetcher,
    InMemoryKeywordIndex,
    InMemoryObjectStorage,
    InMemoryVectorIndex,
    fake_extract,
)

DAILY_TIP = "- เร่งยืนยันรายการโอนที่ค้างอยู่"
SNAPSHOT_CONTRACT_FIELDS = {"id", "kind", "period", "lang", "body", "line_sent", "created_at"}


def _async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
def llm() -> FakeAgentLlm:
    # One scripted daily-enhance tip; every later call (planner/qa) returns
    # None so those paths exercise their deterministic fallbacks.
    return FakeAgentLlm(DAILY_TIP)


@pytest.fixture
def escalator() -> FakeEscalator:
    return FakeEscalator()


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, llm: FakeAgentLlm, escalator: FakeEscalator
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
        agent_runtime=AgentRuntime(llm=llm, escalator=escalator, line_push=None),
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


async def _analytics_run_ids(client: AsyncClient, status: str = "succeeded") -> set[str]:
    response = await client.get(
        "/v1/agents/runs", params={"agent": "analytics", "status": status, "limit": 500}
    )
    assert response.status_code == 200
    return {run["id"] for run in response.json()}


async def test_daily_snapshot_endpoint_runs_the_agent_and_keeps_the_contract(
    client: AsyncClient, llm: FakeAgentLlm
) -> None:
    before = await _analytics_run_ids(client)

    response = await client.post("/v1/reports/daily-snapshot:generate")
    assert response.status_code == 201, response.text
    body = response.json()

    # Response contract IDENTICAL to M1 (the web app depends on it).
    assert set(body) == SNAPSHOT_CONTRACT_FIELDS
    assert body["kind"] == "daily" and body["lang"] == "th"
    assert body["body"].startswith("สรุปประจำวัน")
    assert body["line_sent"] is False

    # LLM enhancement is additive: the tip is appended under the header.
    assert "คำแนะนำวันนี้" in body["body"]
    assert DAILY_TIP in body["body"]
    assert llm.calls and llm.calls[0]["tier"] == "high"

    # The run was traced in agent_runs and succeeded.
    new_runs = await _analytics_run_ids(client) - before
    assert len(new_runs) == 1

    # The stored report matches the response body.
    listed = (await client.get("/v1/reports", params={"kind": "daily"})).json()
    stored = next(r for r in listed if r["id"] == body["id"])
    assert stored["body"] == body["body"]


async def test_trigger_analytics_daily_inline_creates_run_and_report(
    client: AsyncClient,
) -> None:
    before = await _analytics_run_ids(client)

    accepted = await client.post("/v1/agents/analytics-daily:trigger")
    assert accepted.status_code == 202, accepted.text
    payload = accepted.json()
    assert payload["agent"] == "analytics"
    assert "in-process" in payload["detail"]  # broker down -> inline fallback

    new_runs = await _analytics_run_ids(client) - before
    assert len(new_runs) == 1
    reports = (await client.get("/v1/reports", params={"kind": "daily"})).json()
    assert reports  # a report row exists


async def test_unknown_trigger_name_is_a_404_problem(client: AsyncClient) -> None:
    response = await client.post("/v1/agents/no-such-task:trigger")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_costs_endpoint_aggregates_runs_with_budget(client: AsyncClient) -> None:
    assert (await client.post("/v1/reports/daily-snapshot:generate")).status_code == 201

    response = await client.get("/v1/agents/costs", params={"days": 7})
    assert response.status_code == 200
    rows = response.json()
    analytics_rows = [r for r in rows if r["agent"] == "analytics"]
    assert analytics_rows, rows
    row = analytics_rows[-1]  # ordered agent then day -> last is today
    assert set(row) == {
        "agent",
        "day",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "runs",
        "budget_usd",
    }
    assert len(row["day"]) == 10 and row["day"][4] == "-"  # YYYY-MM-DD
    assert row["runs"] >= 1
    assert row["budget_usd"] == pytest.approx(1.0)  # settings.agent_budgets default
    # Ordered agent then day.
    assert rows == sorted(rows, key=lambda r: (r["agent"], r["day"]))


async def test_qa_evaluate_writes_evals_visible_via_endpoint(client: AsyncClient) -> None:
    generated = await client.post("/v1/reports/daily-snapshot:generate")
    assert generated.status_code == 201
    run_ids = await _analytics_run_ids(client)

    accepted = await client.post("/v1/agents/qa-evaluate:trigger")
    assert accepted.status_code == 202
    assert accepted.json()["agent"] == "qa"

    evals = (await client.get("/v1/agents/evals", params={"limit": 500})).json()
    analytics_evals = [e for e in evals if e["run_id"] in run_ids]
    assert analytics_evals, "qa run wrote no evals for analytics runs"
    for row in analytics_evals:
        assert row["agent"] == "analytics"
        assert 0 <= row["score"] <= 100
        assert row["rubric"] in ("report-quality", "run-health")
    # The freshly generated report-producing run scored on report quality.
    assert any(e["rubric"] == "report-quality" for e in analytics_evals)

    # Filter by agent narrows to the same rows.
    filtered = (
        await client.get("/v1/agents/evals", params={"agent": "analytics", "limit": 500})
    ).json()
    assert {e["id"] for e in analytics_evals} <= {e["id"] for e in filtered}


async def test_planner_trigger_produces_planning_report_fallback_path(
    client: AsyncClient,
) -> None:
    accepted = await client.post("/v1/agents/planner:trigger")
    assert accepted.status_code == 202
    assert accepted.json()["agent"] == "planner"

    reports = (await client.get("/v1/reports", params={"kind": "planning"})).json()
    assert reports
    assert reports[0]["body"].startswith("แผนสัปดาห์")  # deterministic fallback (LLM off)
    assert reports[0]["period"].count("-W") == 1  # ISO week


async def test_forced_failure_parks_the_run_and_calls_the_escalator(
    app: FastAPI, client: AsyncClient, escalator: FakeEscalator
) -> None:
    state = app.state
    result = await run_agent(
        "analytics",
        "no-such-task",  # plan() raises a non-retryable AgentError
        settings=state.settings,
        maker=state.sessionmaker,
        runtime=state.agent_runtime,
        kb_adapters=state.kb_adapters,
        competitor_adapters=state.competitor_adapters,
        actor="integration-test",
    )
    assert result["status"] == "parked"
    assert result["run_id"] is not None

    [(record, reason)] = escalator.calls
    assert record.agent == "analytics"
    assert "no-such-task" in reason

    parked = await client.get(
        "/v1/agents/runs", params={"agent": "analytics", "status": "parked", "limit": 500}
    )
    assert result["run_id"] in {run["id"] for run in parked.json()}


async def test_memory_consolidate_trigger_runs_the_memory_agent(
    client: AsyncClient,
) -> None:
    accepted = await client.post("/v1/agents/memory-consolidate:trigger")
    assert accepted.status_code == 202
    runs = await client.get(
        "/v1/agents/runs", params={"agent": "memory", "status": "succeeded", "limit": 10}
    )
    assert runs.json(), "memory consolidation run was not traced"
