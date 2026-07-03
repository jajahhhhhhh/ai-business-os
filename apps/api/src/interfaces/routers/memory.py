"""Agent memory endpoints: remember, recall, consolidate (M2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.memory import MemoryUseCases
from src.infrastructure.adapters import KbAdapters
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import MemorySqlRepository
from src.interfaces.dependencies import KbAdaptersDep, PrincipalDep, SessionDep
from src.interfaces.schemas import ConsolidateOut, MemoryCreate, MemoryOut, MemorySearchOut

router = APIRouter(prefix="/memory", tags=["memory"])


def _use_cases(session: AsyncSession, adapters: KbAdapters) -> MemoryUseCases:
    return MemoryUseCases(
        MemorySqlRepository(session),
        SqlAuditWriter(session),
        vector_index=adapters.vector_index,
        embedder=adapters.embedder,
    )


@router.post("", response_model=MemoryOut, status_code=201)
async def remember(
    payload: MemoryCreate,
    session: SessionDep,
    adapters: KbAdaptersDep,
    principal: PrincipalDep,
) -> MemoryOut:
    memory = await _use_cases(session, adapters).remember(
        kind=payload.kind,
        subject=payload.subject,
        body=payload.body,
        importance=payload.importance,
        expires_at=payload.expires_at,
        actor=principal.actor,
    )
    return MemoryOut.model_validate(memory)


@router.get("/search", response_model=list[MemorySearchOut])
async def recall(
    session: SessionDep,
    adapters: KbAdaptersDep,
    q: Annotated[str, Query(min_length=1, max_length=1_000)],
    kind: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[MemorySearchOut]:
    hits = await _use_cases(session, adapters).recall(q, kind=kind, limit=limit)
    return [
        MemorySearchOut(**MemoryOut.model_validate(hit.memory).model_dump(), score=hit.score)
        for hit in hits
    ]


# Route path ':consolidate' concatenates with the router prefix into
# /v1/memory:consolidate — the same action-suffix style as /v1/jobs/{id}:run.
@router.post(":consolidate", response_model=ConsolidateOut, status_code=202)
async def consolidate(
    session: SessionDep, adapters: KbAdaptersDep, principal: PrincipalDep
) -> ConsolidateOut:
    result = await _use_cases(session, adapters).consolidate(principal.actor)
    return ConsolidateOut(merged=result.merged, expired=result.expired)
