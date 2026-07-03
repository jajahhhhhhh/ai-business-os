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

# Job names that map to Celery tasks (src/worker.py). Anything else is recorded
# but not dispatched; the M4 orchestrator generalizes this registry.
DISPATCHABLE = {
    "sync_bank_alerts": "src.worker.sync_bank_alerts",
    "send_daily_snapshot": "src.worker.send_daily_snapshot",
    "sweep_all_competitors": "src.worker.sweep_all_competitors",
    "weekly_competitor_report": "src.worker.weekly_competitor_report",
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

    task_name = DISPATCHABLE.get(job.name)
    if task_name is not None:
        try:
            from src.worker import celery_app

            celery_app.send_task(task_name)
            return JobRunAccepted(job_id=job_id, detail=f"Dispatched {task_name} to worker")
        except Exception:  # noqa: BLE001 - broker down must not 500 the trigger
            logger.warning("job_dispatch_failed", job=job.name, task=task_name)
            return JobRunAccepted(
                job_id=job_id, detail="Run recorded; broker unreachable, not dispatched"
            )
    return JobRunAccepted(job_id=job_id, detail="Run recorded; no worker task for this job yet")
