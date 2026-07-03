"""Competitor registry, change-event feed and on-demand sweeps (M3).

Route-ordering note: the literal path GET /competitors/changes is registered
BEFORE anything matching /competitors/{competitor_id}... so the global feed
can never be shadowed by (or mistaken for) a competitor id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.competitor_intel import CompetitorIntelUseCases
from src.application.errors import NotFoundError
from src.infrastructure.adapters import CompetitorAdapters
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import (
    CompetitorIntelSqlRepository,
    CompetitorSqlRepository,
    SourceDisplayData,
)
from src.interfaces.dependencies import (
    CompetitorAdaptersDep,
    PrincipalDep,
    SessionDep,
)
from src.interfaces.schemas import (
    ChangeEventFeedOut,
    ChangeEventOut,
    ChangeSeverity,
    CompetitorOut,
    CompetitorRegisterIn,
    CompetitorSourceIn,
    CompetitorSourceOut,
    CompetitorUpdate,
    CompetitorWithSourcesOut,
    SweepAccepted,
)

logger = structlog.get_logger("api.competitors")

router = APIRouter(prefix="/competitors", tags=["competitors"])

SWEEP_TASK = "src.worker.sweep_competitor"


def _use_cases(session: AsyncSession, adapters: CompetitorAdapters) -> CompetitorIntelUseCases:
    return CompetitorIntelUseCases(
        CompetitorIntelSqlRepository(session),
        SqlAuditWriter(session),
        storage=adapters.storage,
        fetcher=adapters.fetcher,
        analyst=adapters.analyst,
    )


def _source_out(source: object) -> CompetitorSourceOut:
    return CompetitorSourceOut.model_validate(source)


def _with_sources(competitor: object, sources: list[SourceDisplayData]) -> CompetitorWithSourcesOut:
    base = CompetitorOut.model_validate(competitor)
    return CompetitorWithSourcesOut(
        **base.model_dump(), sources=[_source_out(source) for source in sources]
    )


# --------------------------------------------------------------- global feed
# Registered first: /changes must never be shadowed by /{competitor_id}.


@router.get("/changes", response_model=list[ChangeEventFeedOut])
async def list_all_changes(
    session: SessionDep,
    since: Annotated[datetime | None, Query()] = None,
    severity: Annotated[ChangeSeverity | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ChangeEventFeedOut]:
    """Global newest-first change feed across all competitors."""
    repo = CompetitorIntelSqlRepository(session)
    events = await repo.list_change_events(
        severity=severity, competitor_id=None, since=since, limit=limit
    )
    return [ChangeEventFeedOut.model_validate(event) for event in events]


# ------------------------------------------------------------------ registry


@router.get("", response_model=list[CompetitorWithSourcesOut])
async def list_competitors(session: SessionDep) -> list[CompetitorWithSourcesOut]:
    competitors = await CompetitorSqlRepository(session).list()
    sources = await CompetitorIntelSqlRepository(session).list_sources(None)
    by_competitor: dict[uuid.UUID, list[SourceDisplayData]] = {}
    for source in sources:
        if source.competitor_id is not None:
            by_competitor.setdefault(source.competitor_id, []).append(source)
    return [_with_sources(c, by_competitor.get(c.id, [])) for c in competitors]


@router.post("", response_model=CompetitorWithSourcesOut, status_code=201)
async def create_competitor(
    payload: CompetitorRegisterIn,
    session: SessionDep,
    adapters: CompetitorAdaptersDep,
    principal: PrincipalDep,
) -> CompetitorWithSourcesOut:
    """Register a competitor + sources. Facebook/OTA URLs -> 422 (§8.4)."""
    result = await _use_cases(session, adapters).register_competitor(
        name=payload.name,
        kind=payload.kind,
        website=payload.website,
        listing_urls=payload.listing_urls,
        sources=[(source.type, source.url) for source in payload.sources or []],
        actor=principal.actor,
    )
    base = CompetitorOut.model_validate(result.competitor)
    return CompetitorWithSourcesOut(
        **base.model_dump(), sources=[_source_out(source) for source in result.sources]
    )


@router.get("/{competitor_id}", response_model=CompetitorWithSourcesOut)
async def get_competitor(competitor_id: uuid.UUID, session: SessionDep) -> CompetitorWithSourcesOut:
    competitor = await CompetitorSqlRepository(session).get(competitor_id)
    if competitor is None:
        raise NotFoundError("competitor", competitor_id)
    sources = await CompetitorIntelSqlRepository(session).list_sources(competitor_id)
    return _with_sources(competitor, sources)


@router.patch("/{competitor_id}", response_model=CompetitorOut)
async def update_competitor(
    competitor_id: uuid.UUID,
    payload: CompetitorUpdate,
    session: SessionDep,
    principal: PrincipalDep,
) -> CompetitorOut:
    changes = payload.model_dump(exclude_unset=True)
    competitor = await CompetitorSqlRepository(session).update(competitor_id, changes)
    await SqlAuditWriter(session).write(
        principal.actor, "competitor.updated", "competitors", competitor_id, changes
    )
    return CompetitorOut.model_validate(competitor)


# ------------------------------------------------------------------- sources


@router.post("/{competitor_id}/sources", response_model=CompetitorSourceOut, status_code=201)
async def add_source(
    competitor_id: uuid.UUID,
    payload: CompetitorSourceIn,
    session: SessionDep,
    adapters: CompetitorAdaptersDep,
    principal: PrincipalDep,
) -> CompetitorSourceOut:
    source = await _use_cases(session, adapters).add_source(
        competitor_id, type=payload.type, url=payload.url, actor=principal.actor
    )
    return _source_out(source)


@router.delete("/{competitor_id}/sources/{source_id}", status_code=204)
async def remove_source(
    competitor_id: uuid.UUID,
    source_id: uuid.UUID,
    session: SessionDep,
    adapters: CompetitorAdaptersDep,
    principal: PrincipalDep,
) -> Response:
    await _use_cases(session, adapters).remove_source(
        competitor_id, source_id, actor=principal.actor
    )
    return Response(status_code=204)


# ------------------------------------------------------------ change history


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


# -------------------------------------------------------------------- sweeps


async def _sweep_inline(request: Request, competitor_id: uuid.UUID) -> None:
    """BackgroundTasks fallback when the Celery broker is unreachable.

    Same degraded-mode tradeoff as the KB upload pipeline: blocks one API
    worker while the sweep runs, no retry — acceptable so on-demand checks
    still work on a single-node deployment with Redis down.
    """
    from src.worker import run_competitor_sweep  # local import: keeps startup light

    await run_competitor_sweep(
        competitor_id,
        maker=request.app.state.sessionmaker,
        adapters=request.app.state.competitor_adapters,
    )


@router.post("/{competitor_id}:check", response_model=SweepAccepted, status_code=202)
async def check_competitor(
    competitor_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    background: BackgroundTasks,
) -> SweepAccepted:
    """Queue an on-demand sweep of one competitor's sources (202)."""
    if await CompetitorSqlRepository(session).get(competitor_id) is None:
        raise NotFoundError("competitor", competitor_id)
    await SqlAuditWriter(session).write(
        principal.actor, "competitor.check_requested", "competitors", competitor_id, None
    )
    # Commit BEFORE dispatching so the worker's own session sees current rows.
    await session.commit()

    try:
        from src.worker import celery_app  # local import, same seam as jobs.py

        celery_app.send_task(SWEEP_TASK, args=[str(competitor_id)], retry=False)
        return SweepAccepted(dispatched=True, detail=f"Dispatched {SWEEP_TASK} to worker")
    except Exception:  # noqa: BLE001 - broker down must not fail the request
        logger.warning("sweep_dispatch_failed", competitor_id=str(competitor_id))
        background.add_task(_sweep_inline, request, competitor_id)
        return SweepAccepted(dispatched=False, detail="Broker unreachable; sweeping in-process")
