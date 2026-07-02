"""Draw-matching rules: outgoing transactions vs pending draws."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from src.domain.draw_matching import PendingDraw, propose_match


def draw(amount: str) -> PendingDraw:
    return PendingDraw(
        id=uuid.uuid4(),
        amount_thb=Decimal(amount),
        requested_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def test_single_equal_amount_matches_unambiguously() -> None:
    target = draw("50000.00")
    proposal = propose_match("out", Decimal("50000.00"), [draw("10000.00"), target])
    assert proposal is not None
    assert proposal.draw_id == target.id
    assert proposal.ambiguous is False


def test_no_equal_amount_means_no_match() -> None:
    assert propose_match("out", Decimal("50000.00"), [draw("49999.99")]) is None


def test_empty_pending_list_means_no_match() -> None:
    assert propose_match("out", Decimal("1.00"), []) is None


def test_incoming_transactions_never_match() -> None:
    assert propose_match("in", Decimal("50000.00"), [draw("50000.00")]) is None


def test_multiple_candidates_propose_oldest_and_flag_ambiguous() -> None:
    older = PendingDraw(
        id=uuid.uuid4(),
        amount_thb=Decimal("50000.00"),
        requested_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    newer = PendingDraw(
        id=uuid.uuid4(),
        amount_thb=Decimal("50000.00"),
        requested_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    proposal = propose_match("out", Decimal("50000.00"), [newer, older])
    assert proposal is not None
    assert proposal.draw_id == older.id
    assert proposal.ambiguous is True


def test_amount_comparison_is_exact_decimal() -> None:
    # 50000 vs 50000.00 are equal Decimals — must match.
    target = draw("50000")
    proposal = propose_match("out", Decimal("50000.00"), [target])
    assert proposal is not None
    assert proposal.draw_id == target.id
