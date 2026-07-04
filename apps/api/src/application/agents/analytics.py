"""Analytics agent (tier HIGH): daily snapshot + weekly competitor report.

Task kinds:
- 'daily-snapshot'   gather -> llm-enhance -> deliver (kind 'daily')
- 'weekly-competitor' gather -> llm-enhance -> deliver (kind 'weekly')

The gather and deliver steps REUSE the M1/M3 use cases through the
AnalyticsGateway — composition lives in exactly one place. llm-enhance is
strictly ADDITIVE: when the LLM is skipped (no key, budget, failure) the
deterministic draft is delivered unchanged, so the report always generates.
Daily enhancement appends a "คำแนะนำวันนี้" section (1-3 bullets); weekly
enhancement is the M3 upgrade path (ChangeAnalyst), moved here.
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

from src.application.agents.ports import AgentLlm, AnalyticsGateway, DeliveredReport
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("agents.analytics")

TASK_DAILY = "daily-snapshot"
TASK_WEEKLY = "weekly-competitor"

STEP_GATHER = "gather"
STEP_ENHANCE = "llm-enhance"
STEP_DELIVER = "deliver"

DAILY_ENHANCE_HEADER_TH = "คำแนะนำวันนี้"
DAILY_ENHANCE_MAX_TOKENS = 500

REPORT_KIND = {TASK_DAILY: "daily", TASK_WEEKLY: "weekly"}

# Inline fallback for packages/prompts/analytics/daily_enhance.th.j2.
# Required template variables: snapshot (the deterministic Thai draft).
DAILY_ENHANCE_PROMPT_FALLBACK_TH = (
    "คุณเป็นผู้ช่วยของเจ้าของโครงการรีโนเวทวิลล่า 2 ไซต์บนเกาะสมุย\n"
    "นี่คือสรุปสถานะประจำวัน:\n\n"
    "{{ snapshot }}\n\n"
    "จากตัวเลขข้างต้น เขียนคำแนะนำที่ลงมือทำได้จริง 1-3 ข้อ (ขึ้นต้นบรรทัดละ '- ')\n"
    "ตอบเฉพาะบรรทัดคำแนะนำเท่านั้น ไม่ต้องมีหัวข้อหรือคำอธิบายอื่น\n"
    "เป็นภาษาไทย ข้อความล้วน (plain text) ไม่ใช้ markdown"
)


class AnalyticsAgent:
    name = "analytics"
    model_tier = ModelTier.HIGH

    def __init__(
        self, gateway: AnalyticsGateway, llm: AgentLlm, *, daily_budget_usd: Decimal
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd
        # Per-run state (a fresh agent instance is built for every run).
        self._draft: str = ""
        self._body: str = ""
        self._period: str = ""
        self._delivered: DeliveredReport | None = None

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind not in REPORT_KIND:
            raise AgentError(f"analytics: unknown task kind {task.kind!r}", retryable=False)
        return [
            Step(STEP_GATHER, {"kind": task.kind}),
            Step(STEP_ENHANCE, {"kind": task.kind}),
            Step(STEP_DELIVER, {"kind": task.kind}),
        ]

    async def execute(self, step: Step) -> StepResult:
        kind = str(step.input["kind"])
        if step.name == STEP_GATHER:
            return await self._gather(step, kind)
        if step.name == STEP_ENHANCE:
            return await self._enhance(step, kind)
        if step.name == STEP_DELIVER:
            return await self._deliver(step, kind)
        raise AgentError(f"analytics: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        # §5.3: retries are the Runner's job; anything that survives them is
        # escalated to the owner and parked, never silently dropped.
        return FailurePolicy.ESCALATE

    # ------------------------------------------------------------- steps

    async def _gather(self, step: Step, kind: str) -> StepResult:
        try:
            if kind == TASK_DAILY:
                composed = await self._gateway.compose_daily()
            else:
                composed = await self._gateway.compose_weekly()
        except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
            raise AgentError(f"gather failed: {exc}", retryable=False) from exc
        self._draft = self._body = composed.body
        self._period = composed.period
        return StepResult(
            step=step, output={"period": composed.period, "chars": len(composed.body)}
        )

    async def _enhance(self, step: Step, kind: str) -> StepResult:
        if kind == TASK_WEEKLY:
            # The M3 upgrade path (never raises; ChangeAnalyst books its own
            # tokens/cost in agent_runs under 'change-analyst').
            self._body = await self._gateway.upgrade_weekly(self._draft) or self._draft
            return StepResult(step=step, output={"enhanced": self._body != self._draft})

        prompt = render_prompt(
            self.name,
            "daily_enhance",
            fallback=DAILY_ENHANCE_PROMPT_FALLBACK_TH,
            variables={"snapshot": self._draft},
        )
        completion = await self._llm.complete(
            tier=str(self.model_tier), prompt=prompt, max_tokens=DAILY_ENHANCE_MAX_TOKENS
        )
        if completion is None or not completion.text.strip():
            logger.info("daily_enhance_skipped", reason="llm unavailable or empty")
            return StepResult(step=step, output={"enhanced": False})
        self._body = f"{self._draft}\n\n{DAILY_ENHANCE_HEADER_TH}\n{completion.text.strip()}"
        return StepResult(
            step=step,
            output={"enhanced": True, "model": completion.model},
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=completion.cost_usd,
        )

    async def _deliver(self, step: Step, kind: str) -> StepResult:
        try:
            delivered = await self._gateway.deliver(
                kind=REPORT_KIND[kind], period=self._period, body=self._body
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
            raise AgentError(f"deliver failed: {exc}", retryable=False) from exc
        self._delivered = delivered
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
