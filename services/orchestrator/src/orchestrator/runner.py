"""Run loop: plan → execute steps → trace → enforce budget → handle failure (§5.3)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from orchestrator.budget import BudgetExceeded, DailyBudget
from orchestrator.contract import Agent, AgentError, Context, FailurePolicy, Task

MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARKED = "parked"       # escalated to owner, awaiting decision
    OVER_BUDGET = "over_budget"


@dataclass
class RunRecord:
    """Mirrors the ``agent_runs`` row (§7)."""

    agent: str
    task_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: RunStatus = RunStatus.RUNNING
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None
    outputs: list[dict[str, Any]] = field(default_factory=list)


class RunSink(Protocol):
    """Persistence seam: the API service provides a Postgres-backed sink;
    tests use an in-memory list."""

    async def save(self, record: RunRecord) -> None: ...


class Escalator(Protocol):
    """Owner notification seam (LINE in production)."""

    async def escalate(self, record: RunRecord, reason: str) -> None: ...


class Runner:
    def __init__(self, budget: DailyBudget, sink: RunSink, escalator: Escalator) -> None:
        self._budget = budget
        self._sink = sink
        self._escalator = escalator

    async def run(self, agent: Agent, task: Task, ctx: Context) -> RunRecord:
        record = RunRecord(agent=agent.name, task_id=task.id)
        try:
            self._budget.check(agent.name)
        except BudgetExceeded as exc:
            record.status = RunStatus.OVER_BUDGET
            record.error = str(exc)
            await self._finish(record, escalate_reason="daily budget exceeded")
            return record

        try:
            steps = agent.plan(task, ctx)
            for step in steps:
                result = await self._execute_with_retry(agent, step)
                record.tokens_in += result.tokens_in
                record.tokens_out += result.tokens_out
                record.cost_usd += result.cost_usd
                record.outputs.append(result.output)
                self._budget.record(agent.name, result.cost_usd)
                self._budget.check(agent.name)
            record.status = RunStatus.SUCCEEDED
            await self._finish(record)
        except BudgetExceeded as exc:
            record.status = RunStatus.OVER_BUDGET
            record.error = str(exc)
            await self._finish(record, escalate_reason="budget exceeded mid-run")
        except AgentError as exc:
            policy = agent.on_failure(exc)
            record.error = str(exc)
            if policy is FailurePolicy.ESCALATE:
                record.status = RunStatus.PARKED
                await self._finish(record, escalate_reason=str(exc))
            else:
                record.status = RunStatus.FAILED
                await self._finish(record)
        return record

    async def _execute_with_retry(self, agent: Agent, step):  # noqa: ANN202
        last_err: AgentError | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return await agent.execute(step)
            except AgentError as exc:
                last_err = exc
                if not exc.retryable:
                    break
                await asyncio.sleep(BACKOFF_BASE_S * (2**attempt))
        assert last_err is not None
        raise last_err

    async def _finish(self, record: RunRecord, escalate_reason: str | None = None) -> None:
        record.finished_at = datetime.now(UTC)
        await self._sink.save(record)
        if escalate_reason is not None:
            # Tasks are parked, never silently dropped (§5.3).
            await self._escalator.escalate(record, escalate_reason)
