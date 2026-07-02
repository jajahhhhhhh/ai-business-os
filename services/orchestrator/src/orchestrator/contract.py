"""The common agent contract (§5.3). Every agent implements this and nothing more."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


class ModelTier(StrEnum):
    """Cheap by default; expensive only for synthesis (§5.1)."""

    LOW = "low"    # classification, extraction, diff summaries
    MID = "mid"    # drafting, scoring explanations
    HIGH = "high"  # reports, strategy, research synthesis


class FailurePolicy(StrEnum):
    RETRY = "retry"        # exponential backoff, max 3
    ESCALATE = "escalate"  # notify owner via LINE with context, park task
    ABORT = "abort"        # unrecoverable, park immediately


@dataclass(frozen=True, slots=True)
class Task:
    kind: str
    payload: dict[str, Any]
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    parent_run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StepResult:
    step: Step
    output: dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")


class AgentError(Exception):
    def __init__(self, message: str, retryable: bool = True) -> None:
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Context:
    """Assembled per run: task + top-k memories + top-k KB chunks (§10),
    capped by token budget. Assembly lives with the Memory agent tooling."""

    memories: list[str]
    kb_chunks: list[str]
    locale: str = "th"


class AgentProtocol(Protocol):
    name: str
    model_tier: ModelTier
    daily_budget_usd: Decimal

    def plan(self, task: Task, ctx: Context) -> list[Step]: ...
    async def execute(self, step: Step) -> StepResult: ...
    def on_failure(self, err: AgentError) -> FailurePolicy: ...


# Convenience alias used across the codebase.
Agent = AgentProtocol
