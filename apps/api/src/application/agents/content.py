"""Content agent (tier HIGH, §5.2 Phase B): SEO brief + brand guide -> an
English marketing draft with a Thai summary for the owner.

Task kind 'content-draft': gather -> draft -> deliver. Gather pulls the most
recent kind='seo' briefs (the SEO agent's output); draft asks the HIGH tier for
one publish-ready English draft plus a Thai summary. When the LLM cannot run
the deterministic marketing.compose_content_fallback skeleton is delivered, so
a draft is ALWAYS produced. Stored as reports kind='content', lang='en' — a
DRAFT FOR APPROVAL: it is not pushed anywhere; the owner reviews it in the
reports archive and the Social agent schedules approved drafts.
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

from src.application.agents.marketing import (
    BRAND_LOCATION,
    BRAND_NAME,
    BRAND_TONE,
    CONTENT_DRAFT_PROMPT_FALLBACK_EN,
    CONTENT_HEADER,
    compose_content_fallback,
    format_briefs,
)
from src.application.agents.planner import current_iso_week
from src.application.agents.ports import AgentLlm, MarketingGateway, ReportRef
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("agents.content")

TASK_CONTENT_DRAFT = "content-draft"

STEP_GATHER = "gather"
STEP_DRAFT = "draft"
STEP_DELIVER = "deliver"

DRAFT_MAX_TOKENS = 900
REPORT_KIND = "content"
BRIEFS_LIMIT = 3


class ContentAgent:
    name = "content"
    model_tier = ModelTier.HIGH

    def __init__(
        self, gateway: MarketingGateway, llm: AgentLlm, *, daily_budget_usd: Decimal
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd
        # Per-run state (a fresh agent instance is built for every run).
        self._briefs: list[ReportRef] = []
        self._body = ""
        self._period = current_iso_week()

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind != TASK_CONTENT_DRAFT:
            raise AgentError(f"content: unknown task kind {task.kind!r}", retryable=False)
        return [Step(STEP_GATHER, {}), Step(STEP_DRAFT, {}), Step(STEP_DELIVER, {})]

    async def execute(self, step: Step) -> StepResult:
        if step.name == STEP_GATHER:
            try:
                self._briefs = await self._gateway.recent_reports("seo", BRIEFS_LIMIT)
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"gather failed: {exc}", retryable=False) from exc
            return StepResult(step=step, output={"briefs": len(self._briefs)})
        if step.name == STEP_DRAFT:
            return await self._draft(step)
        if step.name == STEP_DELIVER:
            try:
                delivered = await self._gateway.deliver(
                    kind=REPORT_KIND, period=self._period, body=self._body, lang="en", line=False
                )
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
        raise AgentError(f"content: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE

    async def _draft(self, step: Step) -> StepResult:
        prompt = render_prompt(
            self.name,
            "content_draft",
            fallback=CONTENT_DRAFT_PROMPT_FALLBACK_EN,
            variables={
                "period": self._period,
                "briefs": format_briefs(self._briefs),
                "tone": BRAND_TONE,
                "brand": BRAND_NAME,
                "location": BRAND_LOCATION,
            },
            locale="en",
        )
        completion = await self._llm.complete(
            tier=str(self.model_tier), prompt=prompt, max_tokens=DRAFT_MAX_TOKENS
        )
        if completion is not None and completion.text.strip():
            body = completion.text.strip()
            if CONTENT_HEADER not in body:  # keep the report machine-checkable
                body = f"{CONTENT_HEADER} — {self._period}\n{body}"
            self._body = body
            return StepResult(
                step=step,
                output={"source": "llm", "model": completion.model},
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=completion.cost_usd,
            )
        logger.info("content_draft_fallback", reason="llm unavailable or empty")
        self._body = compose_content_fallback(self._period, self._briefs)
        return StepResult(step=step, output={"source": "fallback"})
