"""Report archive + daily Thai snapshot (M1) + weekly competitor report (M3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

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


@router.post("/daily-snapshot:generate", response_model=SnapshotReportOut, status_code=201)
async def generate_daily_snapshot(
    session: SessionDep, settings: SettingsDep, principal: PrincipalDep
) -> SnapshotReportOut:
    """Build today's Thai snapshot, store it, and push to LINE when configured.

    Same code path as the 07:30 Celery beat job (src/worker.py).
    """
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
    session: SessionDep,
    settings: SettingsDep,
    adapters: CompetitorAdaptersDep,
    principal: PrincipalDep,
) -> SnapshotReportOut:
    """Compose last week's Thai competitor report, store it, push to LINE.

    Same code path as the Monday 08:00 Celery beat job (src/worker.py).
    """
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
