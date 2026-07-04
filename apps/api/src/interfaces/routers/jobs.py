"""Scheduled-job registry and manual trigger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter

from src.application.errors import NotFoundError
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import JobSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import JobOut, JobRunAccepted

logger = structlog.get_logger("api.jobs")

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Job names that map to Celery tasks (src/worker.py) as (task_name, args).
# Anything else is recorded but not dispatched. M4: the agent-backed jobs
# dispatch src.worker.run_agent_task with (agent, task_kind) args; the legacy
# task names stay stable for the report/consolidation jobs (their bodies now
# route through the agents).
DISPATCHABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    "sync_bank_alerts": ("src.worker.sync_bank_alerts", ()),
    "send_daily_snapshot": ("src.worker.send_daily_snapshot", ()),
    "sweep_all_competitors": ("src.worker.sweep_all_competitors", ()),
    "weekly_competitor_report": ("src.worker.weekly_competitor_report", ()),
    "consolidate_memories": ("src.worker.consolidate_memories", ()),
    "memory_capture_signals": ("src.worker.run_agent_task", ("memory", "capture-signals")),
    "planner_weekly_plan": ("src.worker.run_agent_task", ("planner", "weekly-plan")),
    "qa_evaluate": ("src.worker.run_agent_task", ("qa", "evaluate")),
}


@router.get("", response_model=list[JobOut])
async def list_jobs(session: SessionDep) -> list[JobOut]:
    repo = JobSqlRepository(session)
    return [JobOut.model_validate(job) for job in await repo.list()]


@router.post("/{job_id}:run", response_model=JobRunAccepted, status_code=202)
async def run_job(
    job_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
) -> JobRunAccepted:
    repo = JobSqlRepository(session)
    job = await repo.get(job_id)
    if job is None:
        raise NotFoundError("job", job_id)
    await repo.mark_run_requested(job_id, datetime.now(UTC))
    await SqlAuditWriter(session).write(
        principal.actor, "job.run_requested", "jobs", job_id, {"name": job.name}
    )

    dispatch = DISPATCHABLE.get(job.name)
    if dispatch is not None:
        task_name, args = dispatch
        try:
            from src.worker import celery_app

            celery_app.send_task(task_name, args=list(args))
            return JobRunAccepted(job_id=job_id, detail=f"Dispatched {task_name} to worker")
        except Exception:  # noqa: BLE001 - broker down must not 500 the trigger
            logger.warning("job_dispatch_failed", job=job.name, task=task_name)
            return JobRunAccepted(
                job_id=job_id, detail="Run recorded; broker unreachable, not dispatched"
            )
    return JobRunAccepted(job_id=job_id, detail="Run recorded; no worker task for this job yet")
