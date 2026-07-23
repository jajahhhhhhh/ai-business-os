"""Gateway ports the M4 agents depend on (orchestrator-free).

Infrastructure supplies SQL/LINE/LLM implementations
(src/infrastructure/agent_runtime.py); tests supply fakes (tests/fakes.py).
Model tiers are plain strings ('low'|'mid'|'high') here so this module stays
importable without the orchestrator package.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.application.agents.planning import PlannerInputs
from src.application.lead_discovery import DiscoveryStats


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """One successful completion, priced for the budget ledger."""

    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    model: str


class AgentLlm(Protocol):
    """Budget-aware LLM seam for agent steps.

    Returns None instead of raising when the LLM cannot run — missing key,
    global daily budget exhausted, or every model candidate failed — so
    enhancement stays strictly additive: the deterministic output always
    survives an LLM outage.
    """

    async def complete(
        self,
        *,
        tier: str,
        prompt: str,
        max_tokens: int,
        system: str | None = None,
    ) -> LlmCompletion | None: ...


@dataclass(frozen=True, slots=True)
class ComposedReport:
    body: str
    period: str


@dataclass(frozen=True, slots=True)
class DeliveredReport:
    report_id: uuid.UUID
    kind: str
    period: str | None
    lang: str
    body: str
    line_sent: bool
    created_at: datetime


class AnalyticsGateway(Protocol):
    """Deterministic compose/deliver over the M1/M3 report use cases."""

    async def compose_daily(self) -> ComposedReport: ...
    async def compose_weekly(self) -> ComposedReport: ...

    async def upgrade_weekly(self, draft: str) -> str:
        """M3 ChangeAnalyst upgrade path; never raises (falls back to draft)."""
        ...

    async def deliver(self, *, kind: str, period: str, body: str) -> DeliveredReport: ...


@dataclass(frozen=True, slots=True)
class SignalEvent:
    """A high/critical change event worth remembering."""

    competitor_name: str
    summary: str
    severity: str
    detected_at: datetime


class MemoryGateway(Protocol):
    async def consolidate(self) -> tuple[int, int]:
        """Run the M2 consolidation; returns (merged, expired)."""
        ...

    async def recent_high_severity_events(self, hours: int) -> list[SignalEvent]: ...

    async def find_similar(self, subject: str, body: str) -> list[tuple[str, str]]:
        """Recall candidates as (subject, body) pairs for dedupe."""
        ...

    async def remember_signal(self, *, subject: str, body: str) -> None:
        """remember() with kind='competitor', importance=4."""
        ...


class PlannerGateway(Protocol):
    async def gather_inputs(self) -> PlannerInputs: ...
    async def deliver(self, *, period: str, body: str) -> DeliveredReport: ...


@dataclass(frozen=True, slots=True)
class EvalCandidate:
    """A recent agent run plus its report (when one was produced)."""

    run_id: uuid.UUID
    agent: str
    status: str
    started_at: datetime
    report_kind: str | None = None
    report_body: str | None = None


class QaGateway(Protocol):
    async def eval_candidates(self, days: int) -> list[EvalCandidate]:
        """Last-N-days runs not yet evaluated, newest first."""
        ...

    async def write_eval(
        self, *, run_id: uuid.UUID, rubric: str, score: int, notes: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ContentGap:
    """A competitor content/promo move the SEO agent should react to."""

    competitor_name: str
    summary: str
    category: str


@dataclass(frozen=True, slots=True)
class SeoInputs:
    """Everything the SEO agent reads (gathered by the MarketingGateway)."""

    keyword_themes: tuple[str, ...] = ()
    content_gaps: tuple[ContentGap, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportRef:
    """A previously-delivered marketing report (SEO brief / content draft)."""

    report_id: uuid.UUID
    period: str | None
    body: str
    created_at: datetime


class MarketingGateway(Protocol):
    """M6 shared data seam for the seo/content/social agent family.

    The three agents form a pipeline over the reports table: SEO writes
    kind='seo' briefs, Content reads those briefs and writes kind='content'
    drafts, Social reads the drafts and writes the kind='content-calendar'
    schedule. deliver() is the one write path (report row + audit + optional
    LINE push), mirroring the M4 gateways."""

    async def gather_seo_inputs(self) -> SeoInputs: ...

    async def recent_reports(self, kind: str, limit: int) -> list[ReportRef]:
        """Latest reports of a kind, newest first (upstream pipeline inputs)."""
        ...

    async def deliver(
        self, *, kind: str, period: str, body: str, lang: str, line: bool
    ) -> DeliveredReport: ...


class CustomerDiscoveryGateway(Protocol):
    """M5 lead discovery over LeadDiscoveryUseCases.

    The agent hands its budget-aware AgentLlm down so classification spend is
    booked on the run (Runner + SqlDailyBudget); llm=None means every batch
    scores through the deterministic §8.3 rules."""

    async def discover_source(
        self, source_id: uuid.UUID, llm: AgentLlm | None
    ) -> DiscoveryStats: ...

    async def discover_all(self, llm: AgentLlm | None) -> DiscoveryStats: ...
