"""Agent runtime: explicit state machines over shared state (ADR-4).

Agents are stateless functions over Postgres + Qdrant. Every run is traced,
budgeted, and resumable. No agent-to-agent calls — hand-offs go through the
task queue and shared DB so every step is inspectable.
"""

from orchestrator.budget import BudgetExceeded, DailyBudget
from orchestrator.contract import (
    Agent,
    AgentError,
    FailurePolicy,
    ModelTier,
    Step,
    StepResult,
    Task,
)
from orchestrator.router import ModelRouter

__all__ = [
    "Agent",
    "AgentError",
    "BudgetExceeded",
    "DailyBudget",
    "FailurePolicy",
    "ModelRouter",
    "ModelTier",
    "Step",
    "StepResult",
    "Task",
]
