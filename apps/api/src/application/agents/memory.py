"""Memory agent (tier LOW): consolidation + competitor-signal capture.

Task kinds:
- 'consolidate'      consolidate                (wraps MemoryUseCases.consolidate)
- 'capture-signals'  scan -> capture            (last-24h high/critical change
                     events -> one 'competitor' memory each, importance 4,
                     deduped via recall similarity)

Fully deterministic — no LLM calls; the LOW tier exists so a future
summarizing step has a routing home.
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from orchestrator.contract import (
    AgentError,
    Context,
    FailurePolicy,
    ModelTier,
    Step,
    StepResult,
    Task,
)

from src.application.agents.ports import MemoryGateway, SignalEvent

logger = structlog.get_logger("agents.memory")

TASK_CONSOLIDATE = "consolidate"
TASK_CAPTURE = "capture-signals"

STEP_CONSOLIDATE = "consolidate"
STEP_SCAN = "scan"
STEP_CAPTURE = "capture"

CAPTURE_WINDOW_HOURS = 24


class MemoryAgent:
    name = "memory"
    model_tier = ModelTier.LOW

    def __init__(self, gateway: MemoryGateway, *, daily_budget_usd: Decimal) -> None:
        self._gateway = gateway
        self.daily_budget_usd = daily_budget_usd
        self._events: list[SignalEvent] = []  # per-run state

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind == TASK_CONSOLIDATE:
            return [Step(STEP_CONSOLIDATE, {})]
        if task.kind == TASK_CAPTURE:
            return [
                Step(STEP_SCAN, {"hours": CAPTURE_WINDOW_HOURS}),
                Step(STEP_CAPTURE, {}),
            ]
        raise AgentError(f"memory: unknown task kind {task.kind!r}", retryable=False)

    async def execute(self, step: Step) -> StepResult:
        try:
            if step.name == STEP_CONSOLIDATE:
                merged, expired = await self._gateway.consolidate()
                return StepResult(step=step, output={"merged": merged, "expired": expired})
            if step.name == STEP_SCAN:
                self._events = await self._gateway.recent_high_severity_events(
                    int(step.input.get("hours", CAPTURE_WINDOW_HOURS))
                )
                return StepResult(step=step, output={"events": len(self._events)})
            if step.name == STEP_CAPTURE:
                return await self._capture(step)
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
            raise AgentError(f"memory step {step.name} failed: {exc}", retryable=False) from exc
        raise AgentError(f"memory: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE

    async def _capture(self, step: Step) -> StepResult:
        created = 0
        skipped = 0
        for event in self._events:
            subject = event.competitor_name
            body = event.summary
            similar = await self._gateway.find_similar(subject, body)
            if any(s == subject and b == body for s, b in similar):
                skipped += 1
                continue
            await self._gateway.remember_signal(subject=subject, body=body)
            created += 1
        return StepResult(step=step, output={"created": created, "skipped": skipped})
