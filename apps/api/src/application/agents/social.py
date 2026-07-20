"""Social agent (tier LOW, §5.2 Phase B): approved content drafts -> a 4-week
content calendar (the M6 gate deliverable).

Task kind 'content-calendar': gather -> schedule -> deliver. Fully
deterministic — no LLM calls; scheduling is mechanical (marketing.
schedule_calendar spreads drafts across 4 weeks × 3 weekly slots). The LOW tier
exists so a future caption-polish step has a routing home. Publishing itself is
NOT re-wrapped here: per §7 the Postiz MCP is consumed as-is by the owner/agent
from the delivered calendar. Stored as reports kind='content-calendar',
lang='th', and pushed to LINE so the owner can approve the week's plan.
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

from src.application.agents.marketing import compose_content_calendar
from src.application.agents.ports import MarketingGateway, ReportRef
from src.domain.bank_alerts import BANGKOK_TZ

logger = structlog.get_logger("agents.social")

TASK_CONTENT_CALENDAR = "content-calendar"

STEP_GATHER = "gather"
STEP_SCHEDULE = "schedule"
STEP_DELIVER = "deliver"

REPORT_KIND = "content-calendar"
DRAFTS_LIMIT = 12  # enough to fill 4 weeks × 3 slots without repeating


class SocialAgent:
    name = "social"
    model_tier = ModelTier.LOW

    def __init__(self, gateway: MarketingGateway, *, daily_budget_usd: Decimal) -> None:
        self._gateway = gateway
        self.daily_budget_usd = daily_budget_usd
        # Per-run state (a fresh agent instance is built for every run).
        self._drafts: list[ReportRef] = []
        self._body = ""
        self._period = ""

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind != TASK_CONTENT_CALENDAR:
            raise AgentError(f"social: unknown task kind {task.kind!r}", retryable=False)
        return [Step(STEP_GATHER, {}), Step(STEP_SCHEDULE, {}), Step(STEP_DELIVER, {})]

    async def execute(self, step: Step) -> StepResult:
        try:
            if step.name == STEP_GATHER:
                self._drafts = await self._gateway.recent_reports("content", DRAFTS_LIMIT)
                return StepResult(step=step, output={"drafts": len(self._drafts)})
            if step.name == STEP_SCHEDULE:
                reference = datetime.now(BANGKOK_TZ).date()
                self._body, self._period = compose_content_calendar(reference, self._drafts)
                return StepResult(step=step, output={"period": self._period})
            if step.name == STEP_DELIVER:
                delivered = await self._gateway.deliver(
                    kind=REPORT_KIND, period=self._period, body=self._body, lang="th", line=True
                )
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
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
            raise AgentError(f"social step {step.name} failed: {exc}", retryable=False) from exc
        raise AgentError(f"social: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE
