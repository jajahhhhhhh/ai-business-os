"""Agent runs, costs, evals and manual task triggers (M0 runs; M4 the rest)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Query, Request

from src.application.errors import NotFoundError
from src.infrastructure.change_analyst import bangkok_day_start
from src.infrastructure.repositories import AgentSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep, SettingsDep
from src.interfaces.schemas import (
    AgentCostOut,
    AgentEvalOut,
    AgentRunOut,
    AgentTriggerAccepted,
)

logger = structlog.get_logger("api.agents")

router = APIRouter(prefix="/agents", tags=["agents"])

RUN_AGENT_TASK = "src.worker.run_agent_task"

# Trigger name -> (agent, task kind). Mirrors apps/web/lib/types.ts
# AgentTaskName; unknown names get a 404 problem+json.
TRIGGERS: dict[str, tuple[str, str]] = {
    "analytics-daily": ("analytics", "daily-snapshot"),
    "analytics-weekly": ("analytics", "weekly-competitor"),
    "planner": ("planner", "weekly-plan"),
    "memory-consolidate": ("memory", "consolidate"),
    "memory-capture": ("memory", "capture-signals"),
    "qa-evaluate": ("qa", "evaluate"),
    # M5: sweep every enabled lead source through the discovery pipeline.
    "customer-discovery": ("customer-discovery", "discover-all"),
    # M6 marketing pipeline: seo brief -> content draft -> 4-week calendar.
    "seo": ("seo", "seo-brief"),
    "content": ("content", "content-draft"),
    "social": ("social", "content-calendar"),
}


def resolve_trigger(name: str) -> tuple[str, str]:
    """(agent, task_kind) for a trigger name; NotFoundError -> 404 problem."""
    try:
        return TRIGGERS[name]
    except KeyError:
        raise NotFoundError("agent task", name) from None


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


@router.get("/costs", response_model=list[AgentCostOut])
async def list_costs(
    session: SessionDep,
    settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> list[AgentCostOut]:
    """Per-agent daily spend over the last `days` Bangkok days, ordered
    agent then day. budget_usd is the configured cap (null = unknown agent)."""
    since = bangkok_day_start(datetime.now(UTC)) - timedelta(days=days - 1)
    rows = await AgentSqlRepository(session).daily_costs(since)
    return [
        AgentCostOut(
            agent=row.agent,
            day=row.day.isoformat(),
            cost_usd=row.cost_usd,
            tokens_in=row.tokens_in,
            tokens_out=row.tokens_out,
            runs=row.runs,
            budget_usd=settings.agent_budgets.get(row.agent),
        )
        for row in rows
    ]


@router.get("/evals", response_model=list[AgentEvalOut])
async def list_evals(
    session: SessionDep,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[AgentEvalOut]:
    rows = await AgentSqlRepository(session).list_evals(agent, limit)
    return [
        AgentEvalOut(
            id=row.id,
            run_id=row.run_id,
            agent=row.agent,
            rubric=row.rubric,
            score=int(row.score),
            notes=row.notes,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _run_inline(request: Request, agent: str, task_kind: str, actor: str) -> None:
    """BackgroundTasks fallback when the Celery broker is unreachable (kb
    pattern): the run executes in-process with the app's adapters/runtime.
    run_agent never raises, so this cannot take down the API worker."""
    from src.infrastructure.agent_runtime import run_agent
    from src.interfaces.dependencies import get_agent_runtime

    state = request.app.state
    await run_agent(
        agent,
        task_kind,
        settings=state.settings,
        maker=state.sessionmaker,
        runtime=get_agent_runtime(request),
        kb_adapters=state.kb_adapters,
        competitor_adapters=state.competitor_adapters,
        actor=actor,
    )


@router.post("/{name}:trigger", response_model=AgentTriggerAccepted, status_code=202)
async def trigger_agent(
    name: str,
    request: Request,
    background: BackgroundTasks,
    principal: PrincipalDep,
) -> AgentTriggerAccepted:
    agent, task_kind = resolve_trigger(name)
    try:
        from src.worker import celery_app  # local import, same seam as jobs.py

        celery_app.send_task(RUN_AGENT_TASK, args=[agent, task_kind])
        detail = f"Dispatched {agent}/{task_kind} to worker"
    except Exception:  # noqa: BLE001 - broker down must not fail the trigger
        logger.warning("agent_dispatch_failed", agent=agent, task_kind=task_kind)
        background.add_task(_run_inline, request, agent, task_kind, principal.actor)
        detail = f"Broker unreachable; running {agent}/{task_kind} in-process"
    return AgentTriggerAccepted(agent=agent, detail=detail)
