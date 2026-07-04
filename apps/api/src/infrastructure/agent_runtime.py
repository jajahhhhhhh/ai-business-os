"""Orchestrator integration adapters + the shared run_agent() entrypoint (M4).

This module is the ONLY place the API wires the services/orchestrator package
to Postgres/LINE/Anthropic:

- SqlRunSink        RunRecord -> agent_runs rows (own short-lived session).
- SqlDailyBudget    orchestrator DailyBudget whose ledger is seeded from
                    TODAY's agent_runs cost sums (Bangkok day, matching the
                    M3 ChangeAnalyst and the /v1/agents/costs endpoint), so
                    caps survive restarts. Caps: settings.agent_budgets;
                    global cap: settings.llm_daily_budget_usd.
- LineEscalator     parked-task owner notification via LINE (Thai); logged
                    no-op when LINE is unconfigured — the task is still
                    parked by the Runner (§5.3).
- LlmExecutor       application AgentLlm port over AnthropicLlmClient with
                    ModelRouter tier failover + the global daily LLM budget
                    guard. Returns None instead of raising so enhancement
                    stays additive.
- Sql*Gateway       per-agent gateway ports over the existing use cases.
- run_agent()       builds the agent + Runner and executes one task;
                    NEVER raises (worker contract). Shared by the Celery
                    task, the BackgroundTasks fallback and the synchronous
                    report endpoints.

The orchestrator package is imported normally here: this module is imported
lazily (inside worker task bodies / request handlers), keeping create_app and
the rest of the API importable without it.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import sqlalchemy as sa
import structlog
from orchestrator.budget import DailyBudget
from orchestrator.contract import Context, ModelTier, Task
from orchestrator.router import ModelRouter
from orchestrator.runner import Runner, RunRecord
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.agents.analytics import AnalyticsAgent
from src.application.agents.customer_discovery import CustomerDiscoveryAgent
from src.application.agents.memory import MemoryAgent
from src.application.agents.planner import PlannerAgent
from src.application.agents.planning import CompetitorSignal, PlannerInputs
from src.application.agents.ports import (
    ComposedReport,
    DeliveredReport,
    EvalCandidate,
    LlmCompletion,
    SignalEvent,
)
from src.application.agents.qa import QaAgent
from src.application.bank_transactions import MATCHED
from src.application.competitor_intel import CompetitorIntelUseCases
from src.application.lead_discovery import DiscoveryStats, LeadDiscoveryUseCases
from src.application.memory import MemoryUseCases
from src.application.snapshot import DailySnapshotUseCases
from src.config import Settings
from src.domain.bank_alerts import BANGKOK_TZ
from src.infrastructure.adapters import (
    CompetitorAdapters,
    KbAdapters,
    build_lead_collector,
)
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.change_analyst import AgentRunRecorder, bangkok_day_start
from src.infrastructure.line import LineClient
from src.infrastructure.llm_client import (
    AnthropicLlmClient,
    LlmError,
    ModelCandidate,
)
from src.infrastructure.models import (
    AgentEval,
    AgentRun,
    BankTransaction,
    ChangeEvent,
    Competitor,
    Milestone,
    Report,
    Site,
)
from src.infrastructure.pii import PiiCipher
from src.infrastructure.repositories import (
    CompetitorIntelSqlRepository,
    LeadDiscoverySqlRepository,
    MemorySqlRepository,
    SnapshotSqlRepository,
)

logger = structlog.get_logger("infrastructure.agent_runtime")

ERROR_MAX_CHARS = 500
_CENT4 = Decimal("0.0001")

ESCALATION_MESSAGE_TH = "เอเจนต์ {name} ล้มเหลว: {reason} — งานถูกพักไว้"

AGENT_NAMES = ("analytics", "planner", "memory", "qa", "customer-discovery")

HIGH_SEVERITIES = ("high", "critical")


# --------------------------------------------------------------- budget seam


class CostAggregator(Protocol):
    """Today's per-agent cost sums (fakeable in tests)."""

    async def agent_costs_today(self, now: datetime) -> dict[str, Decimal]: ...


class SqlCostAggregator:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def agent_costs_today(self, now: datetime) -> dict[str, Decimal]:
        day_start = bangkok_day_start(now)
        stmt = (
            sa.select(
                AgentRun.agent,
                sa.func.coalesce(sa.func.sum(AgentRun.cost_usd), sa.literal(Decimal("0"))),
            )
            .where(AgentRun.started_at >= day_start)
            .group_by(AgentRun.agent)
        )
        async with self._maker() as session:
            rows = (await session.execute(stmt)).all()
        return {agent: Decimal(total) for agent, total in rows}


class SqlDailyBudget(DailyBudget):
    """DailyBudget whose ledger is grounded in agent_runs (survives restarts).

    check()/record() keep the exact orchestrator semantics (spent >= cap
    blocks, zero cap means "never runs", global cap on the day's total);
    refresh() must be awaited before Runner.run so today's persisted spend is
    loaded into the in-memory ledger. Within-run spend accumulates in memory
    via record() and lands in agent_runs when the sink saves the run.
    """

    def __init__(
        self,
        *,
        caps: dict[str, Decimal],
        global_cap: Decimal,
        aggregator: CostAggregator,
    ) -> None:
        super().__init__(
            caps={agent: Decimal(cap) for agent, cap in caps.items()},
            global_cap=Decimal(global_cap),
        )
        self._aggregator = aggregator

    async def refresh(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        sums = await self._aggregator.agent_costs_today(now)
        today = self._today()
        self._spent = {(agent, today): Decimal(total) for agent, total in sums.items()}


# ------------------------------------------------------------------ run sink


class SqlRunSink:
    """RunSink writing orchestrator RunRecords to agent_runs.

    Own short-lived session (a run row must persist regardless of any request
    transaction) and never-raise: losing a trace row must not break the run
    or suppress the escalation that follows the save in Runner._finish.
    """

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def save(self, record: RunRecord) -> None:
        try:
            async with self._maker() as session:
                session.add(
                    AgentRun(
                        id=record.id,
                        agent=record.agent,
                        task_id=str(record.task_id),
                        status=getattr(record.status, "value", str(record.status)),
                        model=getattr(record, "model", None),
                        tokens_in=record.tokens_in,
                        tokens_out=record.tokens_out,
                        cost_usd=Decimal(record.cost_usd).quantize(_CENT4, rounding=ROUND_HALF_UP),
                        started_at=record.started_at,
                        finished_at=record.finished_at,
                        error=record.error[:ERROR_MAX_CHARS] if record.error else None,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - trace bookkeeping must not mask the run
            logger.exception("agent_run_save_failed", agent=record.agent)


# ----------------------------------------------------------------- escalator


class LineEscalator:
    """Escalator pushing a Thai parked-task alert to the owner via LINE.

    When LINE is unconfigured this is a logged no-op — the Runner has already
    parked the task (§5.3), so nothing is lost, just not pushed.
    """

    def __init__(self, line: LineClient) -> None:
        self._line = line

    async def escalate(self, record: RunRecord, reason: str) -> None:
        text = ESCALATION_MESSAGE_TH.format(name=record.agent, reason=reason)
        if not self._line.is_configured:
            logger.warning(
                "escalation_line_not_configured",
                agent=record.agent,
                reason=reason,
                run_id=str(record.id),
            )
            return
        await self._line.push_text(text)  # best-effort by LineClient contract


# -------------------------------------------------------------- LLM executor


def _to_candidates(specs: list[Any]) -> list[ModelCandidate]:
    """orchestrator ModelSpec -> structural ModelCandidate (no import cycle)."""
    return [
        ModelCandidate(
            provider=spec.provider,
            model_id=spec.model_id,
            usd_per_mtok_in=spec.usd_per_mtok_in,
            usd_per_mtok_out=spec.usd_per_mtok_out,
        )
        for spec in specs
    ]


class LlmExecutor:
    """AgentLlm implementation: global budget guard + tier failover.

    Returns None (never raises) when the key is missing, the global daily LLM
    budget (settings.llm_daily_budget_usd, ALL agents, Bangkok day) is
    exhausted, or every candidate model fails — callers fall back to their
    deterministic paths. Per-agent caps are the Runner's job (SqlDailyBudget).
    """

    def __init__(
        self,
        *,
        api_key: str,
        daily_budget_usd: Decimal,
        maker: async_sessionmaker[AsyncSession],
        client: Any | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self._client = AnthropicLlmClient(api_key, client=client)
        self._daily_budget_usd = daily_budget_usd
        self._recorder = AgentRunRecorder(maker)
        self._router = router or ModelRouter()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        *,
        tier: str,
        prompt: str,
        max_tokens: int,
        system: str | None = None,
    ) -> LlmCompletion | None:
        if not self._client.is_configured:
            logger.debug("agent_llm_skipped", reason="no api key")
            return None
        now = datetime.now(UTC)
        try:
            spent = await self._recorder.cost_today_usd(now)
        except Exception as exc:  # noqa: BLE001 - budget check must not break callers
            logger.warning("agent_llm_budget_check_failed", error=str(exc))
            return None
        if spent >= self._daily_budget_usd:
            logger.warning(
                "agent_llm_budget_exhausted",
                spent_usd=str(spent),
                budget_usd=str(self._daily_budget_usd),
            )
            return None
        try:
            candidates = _to_candidates(self._router.candidates(ModelTier(tier)))
            response = await self._client.complete_with_failover(
                candidates, system, prompt, max_tokens
            )
        except (LlmError, ValueError) as exc:
            logger.warning("agent_llm_failed", tier=tier, error=str(exc))
            return None
        return LlmCompletion(
            text=response.text,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            model=response.model,
        )


# ----------------------------------------------------------------- gateways


def _delivered(report: Any, line_sent: bool, body: str) -> DeliveredReport:
    return DeliveredReport(
        report_id=report.id,
        kind=report.kind,
        period=report.period,
        lang=report.lang,
        body=report.body or body,
        line_sent=line_sent,
        created_at=report.created_at,
    )


class AnalyticsSqlGateway:
    """AnalyticsGateway over the M1 snapshot + M3 competitor use cases."""

    def __init__(
        self,
        *,
        maker: async_sessionmaker[AsyncSession],
        adapters: CompetitorAdapters,
        line_push: Any | None,
        actor: str,
    ) -> None:
        self._maker = maker
        self._adapters = adapters
        self._line_push = line_push
        self._actor = actor
        self._weekly_events = 0

    def _weekly_use_cases(self, session: AsyncSession) -> CompetitorIntelUseCases:
        return CompetitorIntelUseCases(
            CompetitorIntelSqlRepository(session),
            SqlAuditWriter(session),
            storage=self._adapters.storage,
            fetcher=self._adapters.fetcher,
            analyst=self._adapters.analyst,
            line_push=self._line_push,
        )

    async def compose_daily(self) -> ComposedReport:
        async with self._maker() as session:
            use_cases = DailySnapshotUseCases(
                SnapshotSqlRepository(session), SqlAuditWriter(session)
            )
            body, period = await use_cases.compose()
        return ComposedReport(body=body, period=period)

    async def compose_weekly(self) -> ComposedReport:
        async with self._maker() as session:
            draft, period, events = await self._weekly_use_cases(session).compose_weekly_draft()
        self._weekly_events = events
        return ComposedReport(body=draft, period=period)

    async def upgrade_weekly(self, draft: str) -> str:
        try:
            body = await self._adapters.analyst.upgrade_weekly_report(draft)
        except Exception:  # noqa: BLE001 - analyst contract says never raise; belt
            logger.exception("weekly_upgrade_failed")
            return draft
        return body or draft

    async def deliver(self, *, kind: str, period: str, body: str) -> DeliveredReport:
        async with self._maker() as session:
            if kind == "daily":
                use_cases = DailySnapshotUseCases(
                    SnapshotSqlRepository(session),
                    SqlAuditWriter(session),
                    line_push=self._line_push,
                )
                result = await use_cases.deliver(self._actor, body, period=period)
            else:
                result = await self._weekly_use_cases(session).deliver_weekly(
                    self._actor, body, period=period, events=self._weekly_events
                )
            await session.commit()
        return _delivered(result.report, result.line_sent, body)


class MemorySqlGateway:
    """MemoryGateway over MemoryUseCases + the change_events table."""

    def __init__(
        self,
        *,
        maker: async_sessionmaker[AsyncSession],
        kb_adapters: KbAdapters,
        actor: str,
    ) -> None:
        self._maker = maker
        self._kb = kb_adapters
        self._actor = actor

    def _use_cases(self, session: AsyncSession) -> MemoryUseCases:
        return MemoryUseCases(
            MemorySqlRepository(session),
            SqlAuditWriter(session),
            vector_index=self._kb.vector_index,
            embedder=self._kb.embedder,
        )

    async def consolidate(self) -> tuple[int, int]:
        async with self._maker() as session:
            result = await self._use_cases(session).consolidate(self._actor)
            await session.commit()
        return result.merged, result.expired

    async def recent_high_severity_events(self, hours: int) -> list[SignalEvent]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            sa.select(ChangeEvent, Competitor.name.label("competitor_name"))
            .join(Competitor, ChangeEvent.competitor_id == Competitor.id)
            .where(
                ChangeEvent.detected_at >= since,
                ChangeEvent.severity.in_(HIGH_SEVERITIES),
            )
            .order_by(ChangeEvent.detected_at.desc())
        )
        async with self._maker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            SignalEvent(
                competitor_name=row.competitor_name,
                summary=row.ChangeEvent.summary,
                severity=row.ChangeEvent.severity,
                detected_at=row.ChangeEvent.detected_at,
            )
            for row in rows
        ]

    async def find_similar(self, subject: str, body: str) -> list[tuple[str, str]]:
        async with self._maker() as session:
            hits = await self._use_cases(session).recall(body, kind="competitor", limit=5)
        return [(hit.memory.subject, hit.memory.body) for hit in hits]

    async def remember_signal(self, *, subject: str, body: str) -> None:
        async with self._maker() as session:
            await self._use_cases(session).remember(
                kind="competitor",
                subject=subject,
                body=body,
                importance=4,
                actor=self._actor,
            )
            await session.commit()


class PlannerSqlGateway:
    """PlannerGateway: weekly-plan inputs + planning-report delivery."""

    def __init__(
        self,
        *,
        maker: async_sessionmaker[AsyncSession],
        line_push: Any | None,
        actor: str,
    ) -> None:
        self._maker = maker
        self._line_push = line_push
        self._actor = actor

    async def gather_inputs(self) -> PlannerInputs:
        now = datetime.now(UTC)
        week_ago = now - timedelta(days=7)
        today = now.astimezone(BANGKOK_TZ).date()
        async with self._maker() as session:
            eval_rows = (
                await session.execute(
                    sa.select(AgentRun.agent, sa.func.avg(AgentEval.score))
                    .join(AgentRun, AgentEval.run_id == AgentRun.id)
                    .where(AgentEval.created_at >= week_ago)
                    .group_by(AgentRun.agent)
                )
            ).all()
            milestone_rows = (
                await session.execute(
                    sa.select(Site.name.label("site_name"), Milestone.name)
                    .join(Site, Milestone.site_id == Site.id)
                    .where(
                        Milestone.planned_date.is_not(None),
                        Milestone.planned_date < today,
                        Milestone.status != "done",
                    )
                    .order_by(Milestone.planned_date)
                )
            ).all()
            unconfirmed = (
                await session.execute(
                    sa.select(sa.func.count(BankTransaction.id)).where(
                        BankTransaction.status == MATCHED
                    )
                )
            ).scalar_one()
            signal_rows = (
                await session.execute(
                    sa.select(ChangeEvent, Competitor.name.label("competitor_name"))
                    .join(Competitor, ChangeEvent.competitor_id == Competitor.id)
                    .where(
                        ChangeEvent.detected_at >= week_ago,
                        ChangeEvent.severity.in_(HIGH_SEVERITIES),
                    )
                    .order_by(ChangeEvent.detected_at.desc())
                    .limit(10)
                )
            ).all()
        return PlannerInputs(
            eval_averages={agent: Decimal(avg) for agent, avg in eval_rows},
            overdue_milestones=tuple(f"{row.site_name} — {row.name}" for row in milestone_rows),
            unconfirmed_count=int(unconfirmed),
            competitor_signals=tuple(
                CompetitorSignal(
                    competitor_name=row.competitor_name,
                    summary=row.ChangeEvent.summary,
                    severity=row.ChangeEvent.severity,
                )
                for row in signal_rows
            ),
        )

    async def deliver(self, *, period: str, body: str) -> DeliveredReport:
        now = datetime.now(BANGKOK_TZ)
        line_sent = False
        if self._line_push is not None:
            try:
                line_sent = await self._line_push(body)
            except Exception:  # noqa: BLE001 - push failure is non-fatal by design
                line_sent = False
        async with self._maker() as session:
            report = Report(
                kind="planning",
                period=period,
                lang="th",
                body=body,
                sent_at=now if line_sent else None,
            )
            session.add(report)
            await session.flush()
            await SqlAuditWriter(session).write(
                self._actor,
                "report.generated",
                "reports",
                report.id,
                {"kind": "planning", "period": period, "line_sent": line_sent},
            )
            await session.commit()
        return _delivered(report, line_sent, body)


class LeadDiscoverySqlGateway:
    """CustomerDiscoveryGateway over LeadDiscoveryUseCases (M5).

    One short-lived session per discover call; per-source failures are
    absorbed inside the use case (recorded as sources.last_status), so the
    commit lands whatever the pipeline managed to persist."""

    def __init__(
        self,
        *,
        maker: async_sessionmaker[AsyncSession],
        settings: Settings,
        kb_adapters: KbAdapters,
        competitor_adapters: CompetitorAdapters,
        collector: Any,
        actor: str,
    ) -> None:
        self._maker = maker
        self._settings = settings
        self._kb = kb_adapters
        self._storage = competitor_adapters.storage
        self._collector = collector
        self._actor = actor

    def _use_cases(self, session: AsyncSession) -> LeadDiscoveryUseCases:
        return LeadDiscoveryUseCases(
            LeadDiscoverySqlRepository(session),
            SqlAuditWriter(session),
            storage=self._storage,
            collector=self._collector,
            pii=PiiCipher.from_settings(self._settings),
            embedder=self._kb.embedder,
            vector_index=self._kb.vector_index,
        )

    async def discover_source(self, source_id: uuid.UUID, llm: Any | None) -> DiscoveryStats:
        async with self._maker() as session:
            stats = await self._use_cases(session).discover_source(
                source_id, llm=llm, actor=self._actor
            )
            await session.commit()
        return stats

    async def discover_all(self, llm: Any | None) -> DiscoveryStats:
        async with self._maker() as session:
            stats = await self._use_cases(session).discover_all(llm=llm, actor=self._actor)
            await session.commit()
        return stats


class QaSqlGateway:
    """QaGateway: not-yet-evaluated recent runs + agent_evals writes."""

    CANDIDATE_LIMIT = 500

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def eval_candidates(self, days: int) -> list[EvalCandidate]:
        since = datetime.now(UTC) - timedelta(days=days)
        evaluated = sa.select(AgentEval.run_id)
        stmt = (
            sa.select(
                AgentRun.id,
                AgentRun.agent,
                AgentRun.status,
                AgentRun.started_at,
                Report.kind.label("report_kind"),
                Report.body.label("report_body"),
            )
            .outerjoin(Report, Report.generated_by_run_id == AgentRun.id)
            .where(AgentRun.started_at >= since, AgentRun.id.not_in(evaluated))
            .order_by(AgentRun.started_at.desc())
            .limit(self.CANDIDATE_LIMIT)
        )
        async with self._maker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            EvalCandidate(
                run_id=row.id,
                agent=row.agent,
                status=row.status,
                started_at=row.started_at,
                report_kind=row.report_kind,
                report_body=row.report_body,
            )
            for row in rows
        ]

    async def write_eval(self, *, run_id: uuid.UUID, rubric: str, score: int, notes: str) -> None:
        async with self._maker() as session:
            session.add(AgentEval(run_id=run_id, rubric=rubric, score=Decimal(score), notes=notes))
            await session.commit()


# ------------------------------------------------------------------- runtime


@dataclass
class AgentRuntime:
    """Injectable runtime seam: create_app(agent_runtime=...) takes fakes.

    Budget + run sink are always SQL-backed (built per run from the caller's
    sessionmaker) — integration tests assert on real agent_runs rows; only
    the outward-facing pieces (LLM, LINE, escalation, sampling rng) are
    swappable.
    """

    llm: Any  # application AgentLlm
    escalator: Any  # orchestrator Escalator
    line_push: Any | None = None
    rng: random.Random | None = None
    # M5: LeadCollector seam — None in production means "build the compliance
    # collector lazily from settings" (build_agent); tests inject a fake.
    lead_collector: Any | None = None

    async def aclose(self) -> None:
        for gateway in (self.llm, self.escalator, self.lead_collector):
            aclose = getattr(gateway, "aclose", None)
            if aclose is not None:
                await aclose()


def build_agent_runtime(
    settings: Settings, maker: async_sessionmaker[AsyncSession]
) -> AgentRuntime:
    line = LineClient(settings.line_channel_access_token, settings.line_owner_user_id)
    return AgentRuntime(
        llm=LlmExecutor(
            api_key=settings.anthropic_api_key,
            daily_budget_usd=settings.llm_daily_budget_usd,
            maker=maker,
        ),
        escalator=LineEscalator(line),
        line_push=line.push_text if line.is_configured else None,
        lead_collector=build_lead_collector(settings),
    )


def build_agent(
    agent_name: str,
    *,
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    runtime: AgentRuntime,
    kb_adapters: KbAdapters,
    competitor_adapters: CompetitorAdapters,
    actor: str,
) -> Any:
    budgets = settings.agent_budgets
    cap = budgets.get(agent_name, Decimal("0"))
    if agent_name == "analytics":
        gateway = AnalyticsSqlGateway(
            maker=maker,
            adapters=competitor_adapters,
            line_push=runtime.line_push,
            actor=actor,
        )
        return AnalyticsAgent(gateway, runtime.llm, daily_budget_usd=cap)
    if agent_name == "memory":
        return MemoryAgent(
            MemorySqlGateway(maker=maker, kb_adapters=kb_adapters, actor=actor),
            daily_budget_usd=cap,
        )
    if agent_name == "planner":
        return PlannerAgent(
            PlannerSqlGateway(maker=maker, line_push=runtime.line_push, actor=actor),
            runtime.llm,
            daily_budget_usd=cap,
        )
    if agent_name == "qa":
        return QaAgent(
            QaSqlGateway(maker),
            runtime.llm,
            daily_budget_usd=cap,
            rng=runtime.rng,
        )
    if agent_name == "customer-discovery":
        lead_gateway = LeadDiscoverySqlGateway(
            maker=maker,
            settings=settings,
            kb_adapters=kb_adapters,
            competitor_adapters=competitor_adapters,
            collector=runtime.lead_collector or build_lead_collector(settings),
            actor=actor,
        )
        return CustomerDiscoveryAgent(lead_gateway, runtime.llm, daily_budget_usd=cap)
    raise ValueError(f"unknown agent {agent_name!r}")


async def _link_report_to_run(
    maker: async_sessionmaker[AsyncSession], report_id: str, run_id: uuid.UUID
) -> None:
    """Stamp reports.generated_by_run_id so QA can join reports to runs."""
    try:
        async with maker() as session:
            await session.execute(
                sa.update(Report)
                .where(Report.id == uuid.UUID(report_id))
                .values(generated_by_run_id=run_id)
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - linkage is best-effort bookkeeping
        logger.exception("report_run_link_failed", report_id=report_id, run_id=str(run_id))


async def run_agent(
    agent_name: str,
    task_kind: str,
    *,
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    runtime: AgentRuntime,
    kb_adapters: KbAdapters,
    competitor_adapters: CompetitorAdapters,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one agent task through the orchestrator Runner. NEVER raises.

    Returns a JSON-safe summary: {agent, task_kind, run_id, status, error,
    outputs}. Failure/parking/budget handling is the Runner's job (retry ->
    escalate -> park, §5.3); this wrapper only guards setup errors.
    """
    try:
        agent = build_agent(
            agent_name,
            settings=settings,
            maker=maker,
            runtime=runtime,
            kb_adapters=kb_adapters,
            competitor_adapters=competitor_adapters,
            actor=actor,
        )
        budget = SqlDailyBudget(
            caps=settings.agent_budgets,
            global_cap=settings.llm_daily_budget_usd,
            aggregator=SqlCostAggregator(maker),
        )
        await budget.refresh()
        runner = Runner(budget, SqlRunSink(maker), runtime.escalator)
        record = await runner.run(
            agent,
            Task(kind=task_kind, payload=payload or {}),
            Context(memories=[], kb_chunks=[], locale="th"),
        )
        deliver_output = next(
            (o for o in record.outputs if isinstance(o, dict) and "report_id" in o), None
        )
        if deliver_output is not None:
            await _link_report_to_run(maker, str(deliver_output["report_id"]), record.id)
        status = getattr(record.status, "value", str(record.status))
        logger.info(
            "agent_run_finished",
            agent=agent_name,
            task_kind=task_kind,
            run_id=str(record.id),
            status=status,
        )
        return {
            "agent": agent_name,
            "task_kind": task_kind,
            "run_id": str(record.id),
            "status": status,
            "error": record.error,
            "outputs": record.outputs,
        }
    except Exception as exc:  # noqa: BLE001 - never raise out of worker tasks
        logger.exception("run_agent_failed", agent=agent_name, task_kind=task_kind)
        return {
            "agent": agent_name,
            "task_kind": task_kind,
            "run_id": None,
            "status": "failed",
            "error": str(exc)[:ERROR_MAX_CHARS],
            "outputs": [],
        }
