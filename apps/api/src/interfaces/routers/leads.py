"""Lead pipeline endpoints: cursor-paginated listing and stage transitions."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.application.leads import LeadUseCases
from src.domain.leads import LeadStage
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import LeadSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import LeadListOut, LeadOut, StageChangeIn

router = APIRouter(prefix="/leads", tags=["leads"])


def _use_cases(session: SessionDep) -> LeadUseCases:
    return LeadUseCases(LeadSqlRepository(session), SqlAuditWriter(session))


UseCasesDep = Annotated[LeadUseCases, Depends(_use_cases)]


@router.get("", response_model=LeadListOut)
async def list_leads(
    use_cases: UseCasesDep,
    stage: Annotated[LeadStage | None, Query()] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LeadListOut:
    page = await use_cases.list_leads(
        stage=stage, min_score=min_score, q=q, cursor=cursor, limit=limit
    )
    return LeadListOut(
        items=[LeadOut.model_validate(lead) for lead in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/{lead_id}/stage", response_model=LeadOut)
async def change_stage(
    lead_id: uuid.UUID,
    payload: StageChangeIn,
    use_cases: UseCasesDep,
    principal: PrincipalDep,
) -> LeadOut:
    lead = await use_cases.change_stage(lead_id, payload.stage, principal.actor)
    return LeadOut.model_validate(lead)
