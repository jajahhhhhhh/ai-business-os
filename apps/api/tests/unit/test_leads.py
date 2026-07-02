"""Lead stage-transition rules and intent-score value object."""

import pytest

from src.domain.errors import InvalidScoreError, InvalidStageTransitionError
from src.domain.leads import IntentScore, LeadStage, validate_stage_transition


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (LeadStage.DISCOVERED, LeadStage.QUALIFIED),
        (LeadStage.DISCOVERED, LeadStage.LOST),
        (LeadStage.QUALIFIED, LeadStage.CONTACTED),
        (LeadStage.QUALIFIED, LeadStage.LOST),
        (LeadStage.CONTACTED, LeadStage.WON),
        (LeadStage.CONTACTED, LeadStage.LOST),
    ],
)
def test_allowed_transitions(current: LeadStage, new: LeadStage) -> None:
    validate_stage_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (LeadStage.DISCOVERED, LeadStage.WON),  # no stage skipping
        (LeadStage.DISCOVERED, LeadStage.CONTACTED),
        (LeadStage.QUALIFIED, LeadStage.DISCOVERED),  # no going backwards
        (LeadStage.WON, LeadStage.LOST),  # terminal stages are final
        (LeadStage.LOST, LeadStage.DISCOVERED),
        (LeadStage.QUALIFIED, LeadStage.QUALIFIED),  # self-transition is a no-op error
    ],
)
def test_disallowed_transitions(current: LeadStage, new: LeadStage) -> None:
    with pytest.raises(InvalidStageTransitionError):
        validate_stage_transition(current, new)


def test_intent_score_accepts_bounds() -> None:
    assert IntentScore(0).value == 0
    assert IntentScore(100).value == 100
    assert IntentScore(73).value == 73


@pytest.mark.parametrize("bad", [-1, 101, 1000])
def test_intent_score_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(InvalidScoreError):
        IntentScore(bad)


def test_intent_score_rejects_non_int() -> None:
    with pytest.raises(InvalidScoreError):
        IntentScore(50.5)  # type: ignore[arg-type]
    with pytest.raises(InvalidScoreError):
        IntentScore(True)  # type: ignore[arg-type]


def test_clamped_coerces_into_range() -> None:
    assert IntentScore.clamped(-10).value == 0
    assert IntentScore.clamped(250).value == 100
    assert IntentScore.clamped(49.6).value == 50
    assert IntentScore.clamped(88).value == 88
