"""Agent run history (read-only in M0)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from src.infrastructure.repositories import AgentSqlRepository
from src.interfaces.dependencies import SessionDep
from src.interfaces.schemas import AgentRunOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/runs", response_model=list[AgentRunOut])
async def list_runs(
    session: SessionDep,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AgentRunOut]:
    repo = AgentSqlRepository(session)
    runs = await repo.list_runs(agent, status, limit)
    return [AgentRunOut.model_validate(run) for run in runs]
