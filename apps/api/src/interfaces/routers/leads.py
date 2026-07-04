"""Lead pipeline endpoints: cursor-paginated listing, detail and stage
transitions. The detail view decrypts the PDPA-minimal contact (M5, §8.5)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.application.leads import LeadUseCases
from src.domain.leads import LeadStage
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import LeadSqlRepository
from src.interfaces.dependencies import PiiCipherDep, PrincipalDep, SessionDep
from src.interfaces.schemas import (
    LeadContactOut,
    LeadDetailOut,
    LeadEventOut,
    LeadKind,
    LeadListOut,
    LeadOut,
    LeadScoreOut,
    StageChangeIn,
)

router = APIRouter(prefix="/leads", tags=["leads"])


def _use_cases(session: SessionDep) -> LeadUseCases:
    return LeadUseCases(LeadSqlRepository(session), SqlAuditWriter(session))


UseCasesDep = Annotated[LeadUseCases, Depends(_use_cases)]


@router.get("", response_model=LeadListOut)
async def list_leads(
    use_cases: UseCasesDep,
    stage: Annotated[LeadStage | None, Query()] = None,
    kind: Annotated[LeadKind | None, Query()] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LeadListOut:
    page = await use_cases.list_leads(
        stage=stage, kind=kind, min_score=min_score, q=q, cursor=cursor, limit=limit
    )
    return LeadListOut(
        items=[LeadOut.model_validate(lead) for lead in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{lead_id}", response_model=LeadDetailOut)
async def get_lead(
    lead_id: uuid.UUID,
    use_cases: UseCasesDep,
    cipher: PiiCipherDep,
) -> LeadDetailOut:
    detail = await use_cases.get_detail(lead_id)
    contact_data = cipher.decrypt_contact(detail.lead.contact_json)
    contact = (
        LeadContactOut(
            platform=contact_data.get("platform"),
            handle=contact_data.get("handle"),
            url=contact_data.get("url"),
        )
        if contact_data is not None
        else None
    )
    score = (
        LeadScoreOut(
            value=detail.score.score,
            model_version=detail.score.model_version,
            features=detail.score.features_json,
        )
        if detail.score is not None
        else None
    )
    base = LeadOut.model_validate(detail.lead)
    return LeadDetailOut(
        **base.model_dump(),
        contact=contact,
        events=[
            LeadEventOut(type=event.type, payload=event.payload_json, occurred_at=event.occurred_at)
            for event in detail.events
        ],
        score=score,
        suggestion=detail.suggestion,
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
