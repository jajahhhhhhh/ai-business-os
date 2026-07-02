"""Lead pipeline value objects and stage-transition rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.errors import InvalidScoreError, InvalidStageTransitionError


class LeadStage(StrEnum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    WON = "won"
    LOST = "lost"


_ALLOWED_TRANSITIONS: dict[LeadStage, frozenset[LeadStage]] = {
    LeadStage.DISCOVERED: frozenset({LeadStage.QUALIFIED, LeadStage.LOST}),
    LeadStage.QUALIFIED: frozenset({LeadStage.CONTACTED, LeadStage.LOST}),
    LeadStage.CONTACTED: frozenset({LeadStage.WON, LeadStage.LOST}),
    LeadStage.WON: frozenset(),
    LeadStage.LOST: frozenset(),
}


def validate_stage_transition(current: LeadStage, new: LeadStage) -> None:
    if new not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidStageTransitionError(
            f"Cannot move lead from {current.value!r} to {new.value!r}"
        )


@dataclass(frozen=True, slots=True)
class IntentScore:
    """Lead intent score in [0, 100]. Construction validates; `clamped` coerces."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise InvalidScoreError(f"Intent score must be an int, got {type(self.value).__name__}")
        if not 0 <= self.value <= 100:
            raise InvalidScoreError(f"Intent score must be within 0-100, got {self.value}")

    @classmethod
    def clamped(cls, value: int | float) -> IntentScore:
        return cls(max(0, min(100, round(value))))
