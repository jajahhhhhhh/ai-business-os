"""Draw sequencing and payment rules."""

from decimal import Decimal

import pytest

from src.domain.draws import (
    DrawLine,
    DrawStatus,
    committed_total,
    ensure_mutable,
    next_seq,
    remaining_amount,
    validate_new_draw,
    validate_payment,
)
from src.domain.errors import (
    DrawExceedsRemainingError,
    DrawNotPayableError,
    NonPositiveAmountError,
    PaidDrawImmutableError,
)
from src.domain.money import Money


def _line(seq: int, amount: str, status: DrawStatus = DrawStatus.PENDING) -> DrawLine:
    return DrawLine(seq=seq, amount=Money(Decimal(amount)), status=status)


QUOTATION = Money(Decimal("100000"))


def test_committed_total_excludes_cancelled() -> None:
    draws = [
        _line(1, "40000", DrawStatus.PAID),
        _line(2, "10000", DrawStatus.PENDING),
        _line(3, "99999", DrawStatus.CANCELLED),
    ]
    assert committed_total(draws) == Money(Decimal("50000"))
    assert remaining_amount(QUOTATION, draws) == Money(Decimal("50000"))


def test_next_seq_starts_at_one_and_increments() -> None:
    assert next_seq([]) == 1
    assert next_seq([_line(1, "1"), _line(2, "1")]) == 3
    # Cancelled draws keep their seq; numbering never reuses it.
    assert next_seq([_line(5, "1", DrawStatus.CANCELLED)]) == 6


def test_new_draw_within_remaining_is_allowed() -> None:
    validate_new_draw(QUOTATION, [_line(1, "40000", DrawStatus.PAID)], Money(Decimal("60000")))


def test_new_draw_exceeding_remaining_is_rejected() -> None:
    with pytest.raises(DrawExceedsRemainingError):
        validate_new_draw(
            QUOTATION, [_line(1, "40000", DrawStatus.PAID)], Money(Decimal("60000.01"))
        )


def test_pending_draws_also_reserve_budget() -> None:
    draws = [_line(1, "50000", DrawStatus.PENDING)]
    with pytest.raises(DrawExceedsRemainingError):
        validate_new_draw(QUOTATION, draws, Money(Decimal("50001")))


def test_cancelled_draws_release_budget() -> None:
    draws = [_line(1, "100000", DrawStatus.CANCELLED)]
    validate_new_draw(QUOTATION, draws, Money(Decimal("100000")))


def test_non_positive_draw_is_rejected() -> None:
    with pytest.raises(NonPositiveAmountError):
        validate_new_draw(QUOTATION, [], Money.zero())
    with pytest.raises(NonPositiveAmountError):
        validate_new_draw(QUOTATION, [], Money(Decimal("-1")))


def test_only_pending_draws_are_payable() -> None:
    validate_payment(DrawStatus.PENDING)
    with pytest.raises(DrawNotPayableError):
        validate_payment(DrawStatus.PAID)
    with pytest.raises(DrawNotPayableError):
        validate_payment(DrawStatus.CANCELLED)


def test_paid_draws_are_immutable() -> None:
    ensure_mutable(DrawStatus.PENDING)
    ensure_mutable(DrawStatus.CANCELLED)
    with pytest.raises(PaidDrawImmutableError):
        ensure_mutable(DrawStatus.PAID)
