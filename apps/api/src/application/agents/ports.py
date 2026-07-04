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
