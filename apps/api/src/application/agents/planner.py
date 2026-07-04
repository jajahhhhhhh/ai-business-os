"""Planner agent (tier MID): Monday 08:30 Thai weekly plan.

Task kind 'weekly-plan': gather -> compose -> deliver. Inputs: last week's
agent_evals averages, overdue milestones, matched-but-unconfirmed bank
transaction count, high/critical change events (docs/tech-debt.md is not
readable at runtime and is deliberately skipped). The LLM writes the
"แผนสัปดาห์" top-3 focus list; when it cannot run, the deterministic
rule-based plan (planning.compose_fallback_plan) is delivered instead —
overdue milestones first, unconfirmed payments second, competitor moves
third. Stored as reports kind='planning', period = ISO week, pushed to LINE.
"""

from __future__ import annotations

from datetime import datetime
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

from src.application.agents.planning import (
    PLAN_HEADER_TH,
    WEEKLY_PLAN_PROMPT_FALLBACK_TH,
    PlannerInputs,
    compose_fallback_plan,
    format_inputs_th,
)
from src.application.agents.ports import AgentLlm, PlannerGateway
from src.domain.bank_alerts import BANGKOK_TZ
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("agents.planner")

TASK_WEEKLY_PLAN = "weekly-plan"

STEP_GATHER = "gather"
STEP_COMPOSE = "compose"
STEP_DELIVER = "deliver"

COMPOSE_MAX_TOKENS = 700


def current_iso_week(now: datetime | None = None) -> str:
    """ISO week of today's Bangkok date, e.g. '2026-W27' (the week planned)."""
    local = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
    iso_year, iso_week, _ = local.date().isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


class PlannerAgent:
    name = "planner"
    model_tier = ModelTier.MID

    def __init__(
        self, gateway: PlannerGateway, llm: AgentLlm, *, daily_budget_usd: Decimal
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd
        # Per-run state (a fresh agent instance is built for every run).
        self._inputs = PlannerInputs()
        self._body = ""
        self._period = current_iso_week()

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind != TASK_WEEKLY_PLAN:
            raise AgentError(f"planner: unknown task kind {task.kind!r}", retryable=False)
        return [Step(STEP_GATHER, {}), Step(STEP_COMPOSE, {}), Step(STEP_DELIVER, {})]

    async def execute(self, step: Step) -> StepResult:
        if step.name == STEP_GATHER:
            try:
                self._inputs = await self._gateway.gather_inputs()
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"gather failed: {exc}", retryable=False) from exc
            return StepResult(
                step=step,
                output={
                    "overdue_milestones": len(self._inputs.overdue_milestones),
                    "unconfirmed": self._inputs.unconfirmed_count,
                    "competitor_signals": len(self._inputs.competitor_signals),
                },
            )
        if step.name == STEP_COMPOSE:
            return await self._compose(step)
        if step.name == STEP_DELIVER:
            try:
                delivered = await self._gateway.deliver(period=self._period, body=self._body)
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"deliver failed: {exc}", retryable=False) from exc
            return StepResult(
                step=step,
                output={
                    "report_id": str(delivered.report_id),
                    "kind": delivered.kind,
                    "period": delivered.period,
                    "lang": delivered.lang,
                    "body": delivered.body,
                    "line_sent": delivered.line_sent,
                    "created_at": delivered.created_at.isoformat(),
                },
            )
        raise AgentError(f"planner: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE

    async def _compose(self, step: Step) -> StepResult:
        prompt = render_prompt(
            self.name,
            "weekly_plan",
            fallback=WEEKLY_PLAN_PROMPT_FALLBACK_TH,
            variables={"period": self._period, "inputs": format_inputs_th(self._inputs)},
        )
        completion = await self._llm.complete(
            tier=str(self.model_tier), prompt=prompt, max_tokens=COMPOSE_MAX_TOKENS
        )
        if completion is not None and completion.text.strip():
            body = completion.text.strip()
            if PLAN_HEADER_TH not in body:  # keep the report machine-checkable
                body = f"{PLAN_HEADER_TH} {self._period}\n{body}"
            self._body = body
            return StepResult(
                step=step,
                output={"source": "llm", "model": completion.model},
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=completion.cost_usd,
            )
        logger.info("weekly_plan_fallback", reason="llm unavailable or empty")
        self._body = compose_fallback_plan(self._period, self._inputs)
        return StepResult(step=step, output={"source": "fallback"})
