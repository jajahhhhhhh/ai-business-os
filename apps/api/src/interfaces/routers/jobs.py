"""Scheduled-job registry and manual trigger stub."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from src.application.errors import NotFoundError
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import JobSqlRepository
from src.interfaces.dependencies import PrincipalDep, SessionDep
from src.interfaces.schemas import JobOut, JobRunAccepted

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    # TODO(M4): enqueue the actual Celery task here; until the worker fleet
    # lands this endpoint only records the request and returns 202.
    return JobRunAccepted(job_id=job_id, detail="Run recorded; Celery dispatch lands in M4")
