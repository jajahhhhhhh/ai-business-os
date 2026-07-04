"""Customer Discovery agent (tier LOW, §5.2): classify/score/dedupe leads.

Task kinds:
- 'discover'      {source_id} — one lead source through the §8.1 pipeline
                  (dispatched by POST /v1/sources/{id}:collect).
- 'discover-all'  every enabled lead source (4-hourly beat, §13).

The single step delegates to the CustomerDiscoveryGateway, which wraps
LeadDiscoveryUseCases: per-source failures are absorbed there (recorded as
sources.last_status), so a step failure here means setup/DB trouble — that
escalates per §5.3. The agent's budget-aware LLM is passed down so the ≤10-
item classification batches are booked on this run; when the LLM is skipped
(no key / budget / failure) every candidate scores through the deterministic
§8.3 rules and discovery still completes.
"""

from __future__ import annotations

import uuid
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

from src.application.agents.ports import AgentLlm, CustomerDiscoveryGateway

logger = structlog.get_logger("agents.customer_discovery")

TASK_DISCOVER = "discover"
TASK_DISCOVER_ALL = "discover-all"

STEP_DISCOVER = "discover"
STEP_DISCOVER_ALL = "discover-all"


class CustomerDiscoveryAgent:
    name = "customer-discovery"
    model_tier = ModelTier.LOW

    def __init__(
        self,
        gateway: CustomerDiscoveryGateway,
        llm: AgentLlm,
        *,
        daily_budget_usd: Decimal,
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind == TASK_DISCOVER:
            source_id = task.payload.get("source_id")
            if not source_id:
                raise AgentError(
                    "customer-discovery: 'discover' requires payload.source_id",
                    retryable=False,
                )
            return [Step(STEP_DISCOVER, {"source_id": str(source_id)})]
        if task.kind == TASK_DISCOVER_ALL:
            return [Step(STEP_DISCOVER_ALL, {})]
        raise AgentError(f"customer-discovery: unknown task kind {task.kind!r}", retryable=False)

    async def execute(self, step: Step) -> StepResult:
        try:
            if step.name == STEP_DISCOVER:
                source_id = uuid.UUID(str(step.input["source_id"]))
                stats = await self._gateway.discover_source(source_id, self._llm)
            elif step.name == STEP_DISCOVER_ALL:
                stats = await self._gateway.discover_all(self._llm)
            else:
                raise AgentError(f"customer-discovery: unknown step {step.name!r}", retryable=False)
        except AgentError:
            raise
        except ValueError as exc:  # malformed source_id
            raise AgentError(f"discover failed: {exc}", retryable=False) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
            raise AgentError(f"discover failed: {exc}", retryable=False) from exc
        return StepResult(
            step=step,
            output=stats.as_dict(),
            tokens_in=stats.tokens_in,
            tokens_out=stats.tokens_out,
            cost_usd=stats.cost_usd,
        )

    def on_failure(self, err: AgentError) -> FailurePolicy:
        # §5.3: whatever survives the Runner's retries is escalated + parked.
        return FailurePolicy.ESCALATE
