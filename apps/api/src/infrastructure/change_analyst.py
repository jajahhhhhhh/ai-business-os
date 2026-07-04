"""Anthropic-backed ChangeAnalyst for competitor intel (M3, on the shared
LLM client since M4).

HTTP goes through infrastructure.llm_client.AnthropicLlmClient (x-api-key +
anthropic-version headers, no SDK). Model comes from
settings.change_analyst_model (default claude-haiku-4-5-20251001). Prompts
load from packages/prompts (agent 'change-analyst', tasks 'classify' and
'upgrade_weekly') with the original M3 texts as inline fallbacks.

Design contract (src/application/ports.py ChangeAnalyst):
- classify returns None on ANY problem (no key, over budget, HTTP error,
  unparseable response) — the sweep falls back to the rule-based classifier.
- upgrade_weekly_report NEVER raises and returns the draft unchanged on any
  problem.
- EVERY attempt — success, failure, or budget skip — records an agent_runs
  row (agent='change-analyst', model or 'fallback', tokens, cost, status,
  error) via the RunRecorder, so the daily budget check is grounded in the
  same table the dashboard reads.
- Budget: before each call, today's total cost_usd (Bangkok day, ALL agents)
  is compared against settings.llm_daily_budget_usd; at/over the cap the call
  is skipped and the fallback is used.

Pricing: claude-haiku-4-5 is $1.00 per million input tokens and $5.00 per
million output tokens (platform.claude.com pricing, verified 2026-07-03).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.ports import ChangeClassification
from src.domain.bank_alerts import BANGKOK_TZ
from src.infrastructure.llm_client import (
    ANTHROPIC_API_URL,
    ANTHROPIC_VERSION,
    AnthropicLlmClient,
    LlmError,
)
from src.infrastructure.models import AgentRun
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("infrastructure.change_analyst")

__all__ = [
    "ANTHROPIC_API_URL",
    "ANTHROPIC_VERSION",
    "AgentRunRecorder",
    "AnthropicChangeAnalyst",
    "NullChangeAnalyst",
    "RunRecorder",
    "bangkok_day_start",
    "compute_cost_usd",
    "parse_classification",
]

AGENT_NAME = "change-analyst"
FALLBACK_MODEL_LABEL = "fallback"

# USD per million tokens for claude-haiku-4-5 (see module docstring).
PRICE_IN_USD_PER_MTOK = Decimal("1.00")
PRICE_OUT_USD_PER_MTOK = Decimal("5.00")
_MTOK = Decimal(1_000_000)
_CENT4 = Decimal("0.0001")  # agent_runs.cost_usd is numeric(10,4)

CATEGORIES = ("pricing", "promotion", "content", "listing", "other")
SEVERITIES = ("low", "medium", "high", "critical")

CLASSIFY_MAX_TOKENS = 600
UPGRADE_MAX_TOKENS = 1500
SUMMARY_MAX_CHARS = 160
ERROR_MAX_CHARS = 500

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

ANALYSIS_HEADER_TH = "บทวิเคราะห์"
ACTIONS_HEADER_TH = "3 สิ่งที่ควรทำ"

# Inline fallbacks for packages/prompts/change-analyst/{classify,upgrade_weekly}.th.j2
# (M3 texts verbatim). Required template variables:
#   classify.th.j2       -> competitor_name, diff
#   upgrade_weekly.th.j2 -> draft
CLASSIFY_PROMPT_FALLBACK_TH = (
    "คุณเป็นนักวิเคราะห์คู่แข่งของธุรกิจวิลล่าให้เช่าระดับบูทีคบนเกาะสมุย\n"
    'หน้าเว็บของคู่แข่ง "{{ competitor_name }}" มีการเปลี่ยนแปลง '
    "(unified diff ของข้อความบนหน้าเว็บ):\n\n"
    "{{ diff }}\n\n"
    "วิเคราะห์แล้วตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON "
    "โครงสร้าง:\n"
    '{"category": "pricing|promotion|content|listing|other", '
    '"severity": "low|medium|high|critical", '
    '"summary": "สรุปภาษาไทยไม่เกิน 160 ตัวอักษร"}\n'
    "ใช้ severity 'critical' เฉพาะเมื่อกระทบธุรกิจเราโดยตรงและเร่งด่วน"
)
UPGRADE_PROMPT_FALLBACK_TH = (
    "คุณเป็นที่ปรึกษากลยุทธ์ของเจ้าของวิลล่าให้เช่าระดับบูทีคที่เกาะสมุย\n\n"
    "นี่คือรายงานคู่แข่งประจำสัปดาห์ฉบับร่าง:\n"
    "{{ draft }}\n\n"
    "เขียนรายงานฉบับสมบูรณ์เป็นภาษาไทย โดยคงเนื้อหาเดิมไว้แล้วต่อท้ายด้วย\n"
    f'1) หัวข้อ "{ANALYSIS_HEADER_TH}" — ความหมายของความเคลื่อนไหวเหล่านี้ต่อธุรกิจเรา\n'
    f'2) หัวข้อ "{ACTIONS_HEADER_TH}" — ข้อเสนอแนะ 3 ข้อ เรียงตามความสำคัญ\n'
    "ตอบเป็นข้อความล้วน (plain text) เท่านั้น ห้ามใช้ markdown อ่านง่ายใน LINE"
)


def compute_cost_usd(tokens_in: int, tokens_out: int) -> Decimal:
    """Exact haiku cost, quantized to the 4 decimal places the column holds."""
    cost = (
        Decimal(tokens_in) * PRICE_IN_USD_PER_MTOK + Decimal(tokens_out) * PRICE_OUT_USD_PER_MTOK
    ) / _MTOK
    return cost.quantize(_CENT4, rounding=ROUND_HALF_UP)


def bangkok_day_start(now: datetime) -> datetime:
    """00:00 of `now`'s date on the Bangkok wall clock (tz-aware)."""
    local = now.astimezone(BANGKOK_TZ)
    return datetime(local.year, local.month, local.day, tzinfo=BANGKOK_TZ)


def parse_classification(text: str) -> ChangeClassification | None:
    """Defensively parse the model's JSON verdict.

    Accepts plain JSON, ```json fenced blocks, and JSON embedded in prose
    (first '{' to last '}'). Returns None when nothing usable is found —
    the caller falls back to the rule-based classifier.
    """
    candidate = text.strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    summary = str(data.get("summary", "")).strip()
    if not summary:
        return None
    category = str(data.get("category", "")).strip().lower()
    severity = str(data.get("severity", "")).strip().lower()
    return ChangeClassification(
        category=category if category in CATEGORIES else "other",
        severity=severity if severity in SEVERITIES else "medium",
        summary=summary[:SUMMARY_MAX_CHARS],
    )


class RunRecorder(Protocol):
    """What the analyst needs from the agent_runs table (fakeable in tests)."""

    async def cost_today_usd(self, now: datetime) -> Decimal: ...

    async def record(
        self,
        *,
        agent: str,
        status: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        started_at: datetime,
        finished_at: datetime,
        error: str | None = None,
    ) -> None: ...


class AgentRunRecorder:
    """agent_runs writer/aggregator with its own short-lived sessions.

    Deliberately NOT bound to the request transaction: a run row must persist
    even if the surrounding request rolls back, and the budget check must see
    spend from concurrent workers.
    """

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def cost_today_usd(self, now: datetime) -> Decimal:
        day_start = bangkok_day_start(now)
        stmt = sa.select(
            sa.func.coalesce(sa.func.sum(AgentRun.cost_usd), sa.literal(Decimal("0")))
        ).where(AgentRun.started_at >= day_start)
        async with self._maker() as session:
            total = (await session.execute(stmt)).scalar_one()
        return Decimal(total)

    async def record(
        self,
        *,
        agent: str,
        status: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        started_at: datetime,
        finished_at: datetime,
        error: str | None = None,
    ) -> None:
        async with self._maker() as session:
            session.add(
                AgentRun(
                    agent=agent,
                    status=status,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    started_at=started_at,
                    finished_at=finished_at,
                    error=error,
                )
            )
            await session.commit()


class NullChangeAnalyst:
    """Wired when ANTHROPIC_API_KEY is empty: everything falls back."""

    async def classify(self, diff: str, competitor_name: str) -> ChangeClassification | None:
        return None

    async def upgrade_weekly_report(self, draft: str) -> str:
        return draft


class AnthropicChangeAnalyst:
    """ChangeAnalyst over the Anthropic Messages API (httpx, no SDK)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        daily_budget_usd: Decimal,
        recorder: RunRecorder,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._daily_budget_usd = daily_budget_usd
        self._recorder = recorder
        # Shared Messages client; tests inject a stub http client.
        self._llm = AnthropicLlmClient(api_key, client=client)

    async def aclose(self) -> None:
        await self._llm.aclose()

    async def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int] | None:
        """One Messages API attempt. Returns (text, tokens_in, tokens_out) or
        None after recording the failed/skipped agent_runs row."""
        started_at = datetime.now(UTC)
        if not self._api_key:
            return None
        try:
            spent = await self._recorder.cost_today_usd(started_at)
        except Exception as exc:  # noqa: BLE001 - budget check must not break callers
            logger.warning("llm_budget_check_failed", error=str(exc))
            return None
        if spent >= self._daily_budget_usd:
            logger.warning(
                "llm_budget_exhausted",
                spent_usd=str(spent),
                budget_usd=str(self._daily_budget_usd),
            )
            await self._record(
                status="skipped",
                model=FALLBACK_MODEL_LABEL,
                tokens_in=0,
                tokens_out=0,
                started_at=started_at,
                error=f"daily budget exhausted ({spent} >= {self._daily_budget_usd} USD)",
            )
            return None

        try:
            text, tokens_in, tokens_out = await self._llm.complete(
                self._model, None, prompt, max_tokens
            )
        except LlmError as exc:
            logger.warning("llm_call_failed", model=self._model, error=str(exc))
            await self._record(
                status="failed",
                model=self._model,
                tokens_in=exc.tokens_in,
                tokens_out=exc.tokens_out,
                started_at=started_at,
                error=str(exc)[:ERROR_MAX_CHARS] or exc.__class__.__name__,
            )
            return None

        await self._record(
            status="succeeded",
            model=self._model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            started_at=started_at,
            error=None,
        )
        return text, tokens_in, tokens_out

    async def classify(self, diff: str, competitor_name: str) -> ChangeClassification | None:
        prompt = render_prompt(
            AGENT_NAME,
            "classify",
            fallback=CLASSIFY_PROMPT_FALLBACK_TH,
            variables={"competitor_name": competitor_name, "diff": diff},
        )
        result = await self._call(prompt, CLASSIFY_MAX_TOKENS)
        if result is None:
            return None
        text, _, _ = result
        parsed = parse_classification(text)
        if parsed is None:
            logger.warning("llm_classify_unparseable", competitor=competitor_name)
        return parsed

    async def upgrade_weekly_report(self, draft: str) -> str:
        prompt = render_prompt(
            AGENT_NAME,
            "upgrade_weekly",
            fallback=UPGRADE_PROMPT_FALLBACK_TH,
            variables={"draft": draft},
        )
        result = await self._call(prompt, UPGRADE_MAX_TOKENS)
        if result is None:
            return draft
        text, _, _ = result
        return text or draft

    async def _record(
        self,
        *,
        status: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        started_at: datetime,
        error: str | None,
    ) -> None:
        try:
            await self._recorder.record(
                agent=AGENT_NAME,
                status=status,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=compute_cost_usd(tokens_in, tokens_out),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=error,
            )
        except Exception:  # noqa: BLE001 - bookkeeping must not mask the call result
            logger.exception("llm_run_record_failed", status=status)
