"""QA agent (tier MID): Sunday 04:30 evaluation sweep over agent_runs.

Task kind 'evaluate': sample -> evaluate.

Sampling (§5.3 evaluation policy): ALL last-7-days runs of the HIGH-tier
'analytics' agent plus a 10% random sample of the rest, capped at
SAMPLE_CAP runs (newest first). Runs already holding an eval are excluded by
the gateway, and the qa agent never samples its own runs.

Scoring: deterministic rubric first (rubric.score_report — report exists,
Thai content, required sections per kind, length bounds). For sampled
ANALYTICS reports, an LLM rubric score is requested when the budget allows
and blended 50/50 with the deterministic score (rubric.blend_scores);
otherwise the deterministic score stands alone. Runs without a report get
the 'run-health' rubric (succeeded=100, else 0). One agent_evals row per
sampled run.
"""

from __future__ import annotations

import random
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

from src.application.agents.ports import AgentLlm, EvalCandidate, QaGateway
from src.application.agents.rubric import (
    EVALUATE_PROMPT_FALLBACK_TH,
    RUBRIC_REPORT_QUALITY,
    RUBRIC_RUN_HEALTH,
    blend_scores,
    parse_llm_score,
    score_report,
    score_run_health,
)
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("agents.qa")

TASK_EVALUATE = "evaluate"

STEP_SAMPLE = "sample"
STEP_EVALUATE = "evaluate"

SAMPLE_WINDOW_DAYS = 7
SAMPLE_CAP = 20
RANDOM_SAMPLE_RATE = 0.10
ALWAYS_SAMPLED_AGENT = "analytics"
EVALUATE_MAX_TOKENS = 300
LLM_BODY_MAX_CHARS = 6_000


def select_for_eval(candidates: list[EvalCandidate], rng: random.Random) -> list[EvalCandidate]:
    """Pure sampling: all analytics runs + 10% of the rest, cap SAMPLE_CAP.

    `candidates` is expected newest-first; analytics runs take priority when
    the cap bites. The qa agent's own runs are never selected.
    """
    analytics = [c for c in candidates if c.agent == ALWAYS_SAMPLED_AGENT]
    rest = [c for c in candidates if c.agent not in (ALWAYS_SAMPLED_AGENT, "qa")]
    sampled_rest = [c for c in rest if rng.random() < RANDOM_SAMPLE_RATE]
    return (analytics + sampled_rest)[:SAMPLE_CAP]


class QaAgent:
    name = "qa"
    model_tier = ModelTier.MID

    def __init__(
        self,
        gateway: QaGateway,
        llm: AgentLlm,
        *,
        daily_budget_usd: Decimal,
        rng: random.Random | None = None,
    ) -> None:
        self._gateway = gateway
        self._llm = llm
        self.daily_budget_usd = daily_budget_usd
        self._rng = rng or random.Random()
        self._selected: list[EvalCandidate] = []  # per-run state

    def plan(self, task: Task, ctx: Context) -> list[Step]:
        if task.kind != TASK_EVALUATE:
            raise AgentError(f"qa: unknown task kind {task.kind!r}", retryable=False)
        return [Step(STEP_SAMPLE, {"days": SAMPLE_WINDOW_DAYS}), Step(STEP_EVALUATE, {})]

    async def execute(self, step: Step) -> StepResult:
        if step.name == STEP_SAMPLE:
            try:
                candidates = await self._gateway.eval_candidates(
                    int(step.input.get("days", SAMPLE_WINDOW_DAYS))
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"sample failed: {exc}", retryable=False) from exc
            self._selected = select_for_eval(candidates, self._rng)
            return StepResult(
                step=step,
                output={"candidates": len(candidates), "selected": len(self._selected)},
            )
        if step.name == STEP_EVALUATE:
            return await self._evaluate(step)
        raise AgentError(f"qa: unknown step {step.name!r}", retryable=False)

    def on_failure(self, err: AgentError) -> FailurePolicy:
        return FailurePolicy.ESCALATE

    async def _evaluate(self, step: Step) -> StepResult:
        written = 0
        tokens_in = 0
        tokens_out = 0
        cost = Decimal("0")
        for candidate in self._selected:
            if candidate.report_body is None:
                score, notes = score_run_health(candidate.status)
                rubric = RUBRIC_RUN_HEALTH
            else:
                score, notes = score_report(candidate.report_kind or "", candidate.report_body)
                rubric = RUBRIC_REPORT_QUALITY
                if candidate.agent == ALWAYS_SAMPLED_AGENT:
                    llm_verdict, usage = await self._llm_score(candidate)
                    if usage is not None:
                        tokens_in += usage[0]
                        tokens_out += usage[1]
                        cost += usage[2]
                    if llm_verdict is not None:
                        llm_score, llm_notes = llm_verdict
                        score = blend_scores(score, llm_score)
                        if llm_notes:
                            notes = f"{notes} | LLM: {llm_notes}"
            try:
                await self._gateway.write_eval(
                    run_id=candidate.run_id, rubric=rubric, score=score, notes=notes
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a policy decision
                raise AgentError(f"write_eval failed: {exc}", retryable=False) from exc
            written += 1
        return StepResult(
            step=step,
            output={"evaluated": written},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )

    async def _llm_score(
        self, candidate: EvalCandidate
    ) -> tuple[tuple[int, str] | None, tuple[int, int, Decimal] | None]:
        """(parsed verdict | None, (tokens_in, tokens_out, cost) | None)."""
        prompt = render_prompt(
            self.name,
            "evaluate",
            fallback=EVALUATE_PROMPT_FALLBACK_TH,
            variables={
                "kind": candidate.report_kind or "",
                "body": (candidate.report_body or "")[:LLM_BODY_MAX_CHARS],
            },
        )
        completion = await self._llm.complete(
            tier=str(self.model_tier), prompt=prompt, max_tokens=EVALUATE_MAX_TOKENS
        )
        if completion is None:
            return None, None
        usage = (completion.tokens_in, completion.tokens_out, completion.cost_usd)
        verdict = parse_llm_score(completion.text)
        if verdict is None:
            logger.warning("qa_llm_score_unparseable", run_id=str(candidate.run_id))
        return verdict, usage
