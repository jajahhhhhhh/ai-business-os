"""Competitor registry and change-event feed."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from src.application.errors import NotFoundError
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import CompetitorSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import ChangeEventOut, CompetitorCreate, CompetitorOut

router = APIRouter(prefix="/competitors", tags=["competitors"])


@router.get("", response_model=list[CompetitorOut])
async def list_competitors(session: SessionDep) -> list[CompetitorOut]:
    repo = CompetitorSqlRepository(session)
    return [CompetitorOut.model_validate(c) for c in await repo.list()]


@router.post("", response_model=CompetitorOut, status_code=201)
async def create_competitor(
    payload: CompetitorCreate, session: SessionDep, principal: PrincipalDep
) -> CompetitorOut:
    repo = CompetitorSqlRepository(session)
    competitor = await repo.create(
        payload.name, payload.kind, payload.website, payload.listing_urls
    )
    await SqlAuditWriter(session).write(
        principal.actor, "competitor.created", "competitors", competitor.id, {"name": payload.name}
    )
    return CompetitorOut.model_validate(competitor)


@router.get("/{competitor_id}/changes", response_model=list[ChangeEventOut])
async def list_changes(
    competitor_id: uuid.UUID,
    session: SessionDep,
    since: Annotated[datetime | None, Query()] = None,
) -> list[ChangeEventOut]:
    repo = CompetitorSqlRepository(session)
    if await repo.get(competitor_id) is None:
        raise NotFoundError("competitor", competitor_id)
    changes = await repo.changes_since(competitor_id, since)
    return [ChangeEventOut.model_validate(change) for change in changes]
