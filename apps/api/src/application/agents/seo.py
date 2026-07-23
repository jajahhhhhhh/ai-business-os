"""SEO agent (tier MID, §5.2 Phase B): keyword themes + competitor content
gaps -> an English SEO content brief.

Task kind 'seo-brief': gather -> compose -> deliver. Inputs are the evergreen
keyword themes plus recent high/critical competitor content/promo moves. The
LLM writes the brief; when it cannot run (no key / budget / failure) the
deterministic marketing.compose_seo_brief_fallback brief is delivered instead,
so a brief is ALWAYS produced (enhancement is additive, never load-bearing).
Stored as reports kind='seo', period = ISO week, lang='en'. Not pushed to LINE
(an internal artifact the Content agent consumes; the owner reviews it in the
reports archive).
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
    SEO_BRIEF_PROMPT_FALLBACK_EN,
    SEO_HEADER,
    compose_seo_brief_fallback,
    format_seo_inputs,
)
from src.application.agents.planner import current_iso_week
from src.application.agents.ports import AgentLlm, MarketingGateway, SeoInputs
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("agents.seo")

TASK_SEO_BRIEF = "seo-brief"

STEP_GATHER = "gather"
STEP_COMPOSE = "compose"
STEP_DELIVER = "deliver"

COMPOSE_MAX_TOKENS = 700
REPORT_KIND = "seo"


class SeoAgent:
    name = "seo"
    model_tier = ModelTier.MID

    def __init__(
        self, gateway: MarketingGateway, llm: AgentLlm, *, daily_budget_usd: Decimal
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd
        # Per-run state (a fresh agent instance is built for every run).
        self._inputs = SeoInputs()
        self._body = ""
        self._period = current_iso_week()

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind != TASK_SEO_BRIEF:
            raise AgentError(f"seo: unknown task kind {task.kind!r}", retryable=False)
        return [Step(STEP_GATHER, {}), Step(STEP_COMPOSE, {}), Step(STEP_DELIVER, {})]

    async def execute(self, step: Step) -> StepResult:
        if step.name == STEP_GATHER:
            try:
                self._inputs = await self._gateway.gather_seo_inputs()
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"gather failed: {exc}", retryable=False) from exc
            return StepResult(
                step=step,
                output={
                    "keyword_themes": len(self._inputs.keyword_themes),
                    "content_gaps": len(self._inputs.content_gaps),
                },
            )
        if step.name == STEP_COMPOSE:
            return await self._compose(step)
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
        raise AgentError(f"seo: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE

    async def _compose(self, step: Step) -> StepResult:
        prompt = render_prompt(
            self.name,
            "seo_brief",
            fallback=SEO_BRIEF_PROMPT_FALLBACK_EN,
            variables={"period": self._period, "inputs": format_seo_inputs(self._inputs)},
            locale="en",
        )
        completion = await self._llm.complete(
            tier=str(self.model_tier), prompt=prompt, max_tokens=COMPOSE_MAX_TOKENS
        )
        if completion is not None and completion.text.strip():
            body = completion.text.strip()
            if SEO_HEADER not in body:  # keep the report machine-checkable
                body = f"{SEO_HEADER} — {self._period}\n{body}"
            self._body = body
            return StepResult(
                step=step,
                output={"source": "llm", "model": completion.model},
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=completion.cost_usd,
            )
        logger.info("seo_brief_fallback", reason="llm unavailable or empty")
        self._body = compose_seo_brief_fallback(self._period, self._inputs)
        return StepResult(step=step, output={"source": "fallback"})
