"""Report archive (read-only in M0)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from src.infrastructure.repositories import AgentSqlRepository
from src.interfaces.dependencies import SessionDep
from src.interfaces.schemas import ReportOut

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
