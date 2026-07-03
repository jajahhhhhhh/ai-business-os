"""Anthropic LLM adapter for competitor intel (M3; generalized in M4).

Design contract (src/application/ports.py ChangeAnalyst):
- `None` results mean "unavailable or over budget" — callers fall back to the
  rule-based path, the sweep/report never fails because of the LLM.
- EVERY real API call — success or failure — records an `agent_runs` row
  (agent, status, model, tokens, cost) via AgentRunRecorder, so the daily
  budget check is grounded in the same table the dashboard reads.
- Budget: before each call, today's total cost_usd (Bangkok day) across all
  agents is compared against settings.llm_daily_budget_usd; at/over the cap
  the call is skipped and logged.

The `anthropic` SDK import is lazy (inside _client()): unit tests inject a
stub client and never touch the SDK or the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.ports import ChangeAnalysis, ReportText, WeeklyReportContext
from src.domain.bank_alerts import BANGKOK_TZ
from src.infrastructure.models import AgentRun

logger = structlog.get_logger("infrastructure.llm")

# USD per million tokens (input, output). KEEP IN SYNC with
# docs/tech-debt.md#pricing — verified against platform.claude.com 2026-07-03.
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-4-5-20251001": (Decimal("1.00"), Decimal("5.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
}
# Unknown model -> price as the most expensive entry: overcounting protects
# the daily budget; undercounting would silently blow through it.
_FALLBACK_PRICING = max(MODEL_PRICING_USD_PER_MTOK.values())

_MTOK = Decimal(1_000_000)
_CENT4 = Decimal("0.0001")  # agent_runs.cost_usd is numeric(10,4)

CATEGORIES = ("pricing", "promotion", "content", "availability", "reviews", "other")
SEVERITIES = ("low", "medium", "high", "critical")

ANALYZE_MAX_TOKENS = 500
REPORT_MAX_TOKENS = 1500
ERROR_MAX_CHARS = 500

_ANALYZE_TOOL: dict[str, Any] = {
    "name": "record_change_analysis",
    "description": "บันทึกผลการวิเคราะห์การเปลี่ยนแปลงบนเว็บไซต์คู่แข่ง",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary_th": {
                "type": "string",
                "description": "สรุปการเปลี่ยนแปลงเป็นภาษาไทย สั้น กระชับ (1-2 ประโยค)",
            },
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "severity": {"type": "string", "enum": list(SEVERITIES)},
        },
        "required": ["summary_th", "category", "severity"],
    },
}


def compute_cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Exact cost from the per-model pricing table, quantized to 4 places."""
    price_in, price_out = MODEL_PRICING_USD_PER_MTOK.get(model, _FALLBACK_PRICING)
    cost = (Decimal(tokens_in) * price_in + Decimal(tokens_out) * price_out) / _MTOK
    return cost.quantize(_CENT4, rounding=ROUND_HALF_UP)


def bangkok_day_start(now: datetime) -> datetime:
    """00:00 of `now`'s date on the Bangkok wall clock (tz-aware)."""
    local = now.astimezone(BANGKOK_TZ)
    return datetime(local.year, local.month, local.day, tzinfo=BANGKOK_TZ)


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

    @property
    def is_available(self) -> bool:
        return False

    async def analyze_change(
        self, competitor_name: str, url: str, diff_excerpt: str
    ) -> ChangeAnalysis | None:
        return None

    async def compose_weekly_report(self, context: WeeklyReportContext) -> ReportText | None:
        return None


class AnthropicChangeAnalyst:
    """ChangeAnalyst implementation over the Anthropic Messages API.

    analyze_change uses the low-tier model with a forced tool call (structured
    output); compose_weekly_report uses the high-tier model for Thai synthesis
    (§5.2: cheap model for classification, expensive only for reports).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_low: str,
        model_high: str,
        daily_budget_usd: Decimal,
        recorder: RunRecorder,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_low = model_low
        self._model_high = model_high
        self._daily_budget_usd = daily_budget_usd
        self._recorder = recorder
        self._client = client  # tests inject a stub; production builds lazily

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def _client_or_build(self) -> Any:
        if self._client is None:
            # Lazy: the SDK is only imported when a real call is about to
            # happen, so unit tests with a stub client never need `anthropic`.
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def _within_budget(self, agent: str, now: datetime) -> bool:
        spent = await self._recorder.cost_today_usd(now)
        if spent >= self._daily_budget_usd:
            logger.warning(
                "llm_budget_exhausted",
                agent=agent,
                spent_usd=str(spent),
                budget_usd=str(self._daily_budget_usd),
            )
            return False
        return True

    async def analyze_change(
        self, competitor_name: str, url: str, diff_excerpt: str
    ) -> ChangeAnalysis | None:
        if not self.is_available:
            return None
        started_at = datetime.now(UTC)
        if not await self._within_budget("competitor-diff", started_at):
            return None

        prompt = (
            "คุณเป็นนักวิเคราะห์คู่แข่งของธุรกิจวิลล่าให้เช่าระดับบูทีคบนเกาะสมุย\n"
            f'หน้าเว็บของคู่แข่ง "{competitor_name}" ({url}) มีการเปลี่ยนแปลงดังนี้ '
            "(unified diff ของข้อความบนหน้าเว็บ):\n\n"
            f"{diff_excerpt}\n\n"
            "สรุปสาระสำคัญของการเปลี่ยนแปลงเป็นภาษาไทย พร้อมจัดประเภทและระดับความสำคัญ "
            "ผ่านเครื่องมือ record_change_analysis เท่านั้น "
            "(ใช้ severity 'critical' เฉพาะเมื่อกระทบธุรกิจเราโดยตรงและเร่งด่วน)"
        )
        try:
            response = await self._client_or_build().messages.create(
                model=self._model_low,
                max_tokens=ANALYZE_MAX_TOKENS,
                tools=[_ANALYZE_TOOL],
                tool_choice={"type": "tool", "name": "record_change_analysis"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - LLM failure must not break the sweep
            await self._record_failure("competitor-diff", self._model_low, started_at, exc)
            return None

        tokens_in, tokens_out = _usage(response)
        cost_usd = compute_cost_usd(self._model_low, tokens_in, tokens_out)
        tool_input = _tool_input(response, _ANALYZE_TOOL["name"])
        status = "succeeded" if tool_input is not None else "failed"
        await self._recorder.record(
            agent="competitor-diff",
            status=status,
            model=self._model_low,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            error=None if tool_input is not None else "no tool_use block in response",
        )
        if tool_input is None:
            logger.warning("llm_analyze_no_tool_use", competitor=competitor_name)
            return None

        summary = str(tool_input.get("summary_th", "")).strip()
        category = str(tool_input.get("category", "other"))
        severity = str(tool_input.get("severity", "low"))
        if not summary:
            return None
        return ChangeAnalysis(
            summary_th=summary,
            category=category if category in CATEGORIES else "other",
            severity=severity if severity in SEVERITIES else "low",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

    async def compose_weekly_report(self, context: WeeklyReportContext) -> ReportText | None:
        if not self.is_available:
            return None
        started_at = datetime.now(UTC)
        if not await self._within_budget("competitor-report", started_at):
            return None

        event_lines = "\n".join(
            f"- [{event.severity}] {event.competitor_name} ({event.category}): {event.summary}"
            for event in context.events
        ) or "(ไม่มีเหตุการณ์)"
        prompt = (
            "คุณเป็นที่ปรึกษากลยุทธ์ของเจ้าของวิลล่าให้เช่าระดับบูทีคที่ลิปะน้อย เกาะสมุย "
            "(กำลังรีโนเวท ยังไม่เปิดรับแขก)\n\n"
            f"ช่วงรายงาน: {context.period_start.isoformat()} ถึง {context.period_end.isoformat()}\n"
            f"เหตุการณ์ความเคลื่อนไหวของคู่แข่งในรอบสัปดาห์:\n{event_lines}\n\n"
            f"รายงานฉบับร่าง (template):\n{context.template_report}\n\n"
            "เขียนรายงานผู้บริหารภาษาไทยฉบับสมบูรณ์ โครงสร้าง:\n"
            "1) สรุปว่ามีอะไรเปลี่ยนแปลงบ้าง (จัดกลุ่มตามคู่แข่ง)\n"
            "2) ความหมายต่อธุรกิจเรา (so-what)\n"
            "3) ข้อเสนอแนะการตอบสนอง 3 ข้อ เรียงตามลำดับความสำคัญ\n"
            "ใช้ข้อความล้วน (plain text) อ่านง่ายใน LINE ตอบเป็นภาษาไทยเท่านั้น"
        )
        try:
            response = await self._client_or_build().messages.create(
                model=self._model_high,
                max_tokens=REPORT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 - report falls back to the template
            await self._record_failure("competitor-report", self._model_high, started_at, exc)
            return None

        tokens_in, tokens_out = _usage(response)
        cost_usd = compute_cost_usd(self._model_high, tokens_in, tokens_out)
        text = "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        status = "succeeded" if text else "failed"
        await self._recorder.record(
            agent="competitor-report",
            status=status,
            model=self._model_high,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            error=None if text else "empty text response",
        )
        if not text:
            return None
        return ReportText(
            text=text, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd
        )

    async def _record_failure(
        self, agent: str, model: str, started_at: datetime, exc: Exception
    ) -> None:
        logger.warning("llm_call_failed", agent=agent, model=model, error=str(exc))
        try:
            await self._recorder.record(
                agent=agent,
                status="failed",
                model=model,
                tokens_in=0,
                tokens_out=0,
                cost_usd=Decimal("0"),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                error=str(exc)[:ERROR_MAX_CHARS] or exc.__class__.__name__,
            )
        except Exception:  # noqa: BLE001 - bookkeeping must not mask the original failure
            logger.exception("llm_run_record_failed", agent=agent)


def _usage(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def _tool_input(response: Any, tool_name: str) -> dict[str, Any] | None:
    for block in getattr(response, "content", ()) or ():
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == tool_name:
            data = getattr(block, "input", None)
            return dict(data) if isinstance(data, dict) else None
    return None
