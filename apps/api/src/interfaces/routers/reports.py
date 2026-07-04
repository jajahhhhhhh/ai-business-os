"""Report archive + daily Thai snapshot (M1) + weekly competitor report (M3).

Since M4 the two :generate endpoints execute the ANALYTICS AGENT synchronously
(gather -> llm-enhance -> deliver through the orchestrator Runner, traced in
agent_runs) and return the exact same SnapshotReportOut contract the web app
depends on. When the agent path cannot deliver — orchestrator missing, agent
over its daily cap, run parked — the endpoint falls back to the original
deterministic use-case path so a report is ALWAYS generated (enhancement is
additive, never load-bearing).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Query, Request

from src.application.competitor_intel import CompetitorIntelUseCases
from src.application.snapshot import DailySnapshotUseCases
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.line import LineClient
from src.infrastructure.repositories import (
    AgentSqlRepository,
    CompetitorIntelSqlRepository,
    SnapshotSqlRepository,
)
from src.interfaces.dependencies import (
    CompetitorAdaptersDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
)
from src.interfaces.schemas import ReportOut, SnapshotReportOut

logger = structlog.get_logger("api.reports")

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportOut])
async def list_reports(
    session: SessionDep,
    kind: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReportOut]:
    repo = AgentSqlRepository(session)
    reports = await repo.list_reports(kind, limit)
    return [ReportOut.model_validate(report) for report in reports]


async def _generate_via_agent(
    request: Request, task_kind: str, actor: str
) -> SnapshotReportOut | None:
    """Run the analytics agent inline; None when it did not deliver a report
    (over budget / parked / orchestrator unavailable) — callers fall back."""
    from src.infrastructure.agent_runtime import run_agent
    from src.interfaces.dependencies import get_agent_runtime

    state = request.app.state
    result = await run_agent(
        "analytics",
        task_kind,
        settings=state.settings,
        maker=state.sessionmaker,
        runtime=get_agent_runtime(request),
        kb_adapters=state.kb_adapters,
        competitor_adapters=state.competitor_adapters,
        actor=actor,
    )
    output = next((o for o in result["outputs"] if isinstance(o, dict) and "report_id" in o), None)
    if output is None:
        logger.warning(
            "report_agent_no_delivery",
            task_kind=task_kind,
            status=result["status"],
            error=result["error"],
        )
        return None
    return SnapshotReportOut(
        id=uuid.UUID(output["report_id"]),
        kind=output["kind"],
        period=output["period"],
        lang=output["lang"],
        body=output["body"],
        line_sent=output["line_sent"],
        created_at=datetime.fromisoformat(output["created_at"]),
    )


async def _agent_path(request: Request, task_kind: str, actor: str) -> SnapshotReportOut | None:
    try:
        return await _generate_via_agent(request, task_kind, actor)
    except Exception:  # noqa: BLE001 - agent path is best-effort; fallback below
        logger.exception("report_agent_path_failed", task_kind=task_kind)
        return None


@router.post("/daily-snapshot:generate", response_model=SnapshotReportOut, status_code=201)
async def generate_daily_snapshot(
    request: Request, session: SessionDep, settings: SettingsDep, principal: PrincipalDep
) -> SnapshotReportOut:
    """Build today's Thai snapshot, store it, and push to LINE when configured.

    Same code path as the 07:30 Celery beat job (analytics agent since M4);
    the response contract is unchanged from M1.
    """
    generated = await _agent_path(request, "daily-snapshot", principal.actor)
    if generated is not None:
        return generated

    # Deterministic fallback: the original M1 path (no LLM enhancement).
    line = LineClient(settings.line_channel_access_token, settings.line_owner_user_id)
    use_cases = DailySnapshotUseCases(
        SnapshotSqlRepository(session),
        SqlAuditWriter(session),
        line_push=line.push_text if line.is_configured else None,
    )
    result = await use_cases.generate(principal.actor)
    return SnapshotReportOut(
        id=result.report.id,
        kind=result.report.kind,
        period=result.report.period,
        lang=result.report.lang,
        body=result.report.body or "",
        line_sent=result.line_sent,
        created_at=result.report.created_at,
    )


@router.post("/weekly-competitor:generate", response_model=SnapshotReportOut, status_code=201)
async def generate_weekly_competitor_report(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    adapters: CompetitorAdaptersDep,
    principal: PrincipalDep,
) -> SnapshotReportOut:
    """Compose last week's Thai competitor report, store it, push to LINE.

    Same code path as the Monday 08:00 Celery beat job (analytics agent since
    M4); the response contract is unchanged from M3.
    """
    generated = await _agent_path(request, "weekly-competitor", principal.actor)
    if generated is not None:
        return generated

    # Deterministic fallback: the original M3 path.
    line = LineClient(settings.line_channel_access_token, settings.line_owner_user_id)
    use_cases = CompetitorIntelUseCases(
        CompetitorIntelSqlRepository(session),
        SqlAuditWriter(session),
        storage=adapters.storage,
        fetcher=adapters.fetcher,
        analyst=adapters.analyst,
        line_push=line.push_text if line.is_configured else None,
    )
    result = await use_cases.generate_weekly_report(principal.actor)
    return SnapshotReportOut(
        id=result.report.id,
        kind=result.report.kind,
        period=result.report.period,
        lang=result.report.lang,
        body=result.report.body or "",
        line_sent=result.line_sent,
        created_at=result.report.created_at,
    )
