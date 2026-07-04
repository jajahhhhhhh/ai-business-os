"""Lead-source registry + on-demand collection (M5, /v1/sources).

Lead sources only: sources rows with competitor_id IS NULL. Competitor-owned
sources are managed under /v1/competitors and answer 404 here. §8.4 is
enforced at the boundary: rss URLs pass the HARD_BLOCKLIST check (facebook /
OTA domains -> 422 with a Thai policy explanation), reddit sources are
subreddit-config only (official API collection).

POST /{id}:collect dispatches the customer-discovery agent ('discover') via
Celery, with the BackgroundTasks in-process fallback when the broker is
unreachable (kb/competitors pattern).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Request, Response

from src.application.lead_discovery import LeadSourceUseCases
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import LeadSourceSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import (
    LeadCollectAccepted,
    LeadSourceCreateIn,
    LeadSourceOut,
    LeadSourceUpdateIn,
)

logger = structlog.get_logger("api.sources")

router = APIRouter(prefix="/sources", tags=["sources"])

COLLECT_TASK = "src.worker.collect_lead_source"
AGENT_NAME = "customer-discovery"
TASK_KIND = "discover"


def _use_cases(session: SessionDep) -> LeadSourceUseCases:
    return LeadSourceUseCases(LeadSourceSqlRepository(session), SqlAuditWriter(session))


@router.get("", response_model=list[LeadSourceOut])
async def list_sources(session: SessionDep) -> list[LeadSourceOut]:
    use_cases = _use_cases(session)
    return [LeadSourceOut.model_validate(source) for source in await use_cases.list_sources()]


@router.post("", response_model=LeadSourceOut, status_code=201)
async def create_source(
    payload: LeadSourceCreateIn,
    session: SessionDep,
    principal: PrincipalDep,
) -> LeadSourceOut:
    """Register a lead source. Blocklisted rss URLs -> 422 (§8.4)."""
    source = await _use_cases(session).create_source(
        name=payload.name,
        type=payload.type,
        url=payload.url,
        config=payload.config,
        rate_limit_per_hr=payload.rate_limit_per_hr,
        actor=principal.actor,
    )
    return LeadSourceOut.model_validate(source)


@router.patch("/{source_id}", response_model=LeadSourceOut)
async def update_source(
    source_id: uuid.UUID,
    payload: LeadSourceUpdateIn,
    session: SessionDep,
    principal: PrincipalDep,
) -> LeadSourceOut:
    changes = payload.model_dump(exclude_unset=True)
    source = await _use_cases(session).update_source(source_id, changes, principal.actor)
    return LeadSourceOut.model_validate(source)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> Response:
    await _use_cases(session).delete_source(source_id, principal.actor)
    return Response(status_code=204)


async def _collect_inline(request: Request, source_id: uuid.UUID, actor: str) -> None:
    """BackgroundTasks fallback when the Celery broker is unreachable.

    Runs the customer-discovery agent in-process through run_agent (never
    raises), so on-demand collection still works with Redis down.
    """
    from src.infrastructure.agent_runtime import run_agent
    from src.interfaces.dependencies import get_agent_runtime

    state = request.app.state
    await run_agent(
        AGENT_NAME,
        TASK_KIND,
        settings=state.settings,
        maker=state.sessionmaker,
        runtime=get_agent_runtime(request),
        kb_adapters=state.kb_adapters,
        competitor_adapters=state.competitor_adapters,
        actor=actor,
        payload={"source_id": str(source_id)},
    )


@router.post("/{source_id}:collect", response_model=LeadCollectAccepted, status_code=202)
async def collect_source(
    source_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    background: BackgroundTasks,
) -> LeadCollectAccepted:
    """Queue an on-demand collection run for one lead source (202)."""
    await _use_cases(session).get_lead_source(source_id)  # 404 for non-lead sources
    await SqlAuditWriter(session).write(
        principal.actor, "lead_source.collect_requested", "sources", source_id, None
    )
    # Commit BEFORE dispatching so the worker's own session sees current rows.
    await session.commit()

    try:
        from src.worker import celery_app  # local import, same seam as jobs.py

        celery_app.send_task(COLLECT_TASK, args=[str(source_id)], retry=False)
        return LeadCollectAccepted(dispatched=True, detail=f"Dispatched {COLLECT_TASK} to worker")
    except Exception:  # noqa: BLE001 - broker down must not fail the request
        logger.warning("collect_dispatch_failed", source_id=str(source_id))
        background.add_task(_collect_inline, request, source_id, principal.actor)
        return LeadCollectAccepted(
            dispatched=False, detail="Broker unreachable; collecting in-process"
        )
