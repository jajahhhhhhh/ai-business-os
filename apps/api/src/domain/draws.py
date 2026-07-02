"""Contractor draw sequencing and payment rules (Phase A renovation)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from src.domain.errors import (
    DrawExceedsRemainingError,
    DrawNotPayableError,
    NonPositiveAmountError,
    PaidDrawImmutableError,
)
from src.domain.money import Money


class DrawStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DrawLine:
    """The minimal projection of a draw the sequencing rules need."""

    seq: int
    amount: Money
    status: DrawStatus


def committed_total(draws: Iterable[DrawLine], currency: str = "THB") -> Money:
    """Sum of all non-cancelled draws (pending draws still reserve budget)."""
    total = Money.zero(currency)
    for draw in draws:
        if draw.status is not DrawStatus.CANCELLED:
            total = total + draw.amount
    return total


def remaining_amount(quotation_total: Money, draws: Iterable[DrawLine]) -> Money:
    return quotation_total - committed_total(draws, quotation_total.currency)


def next_seq(draws: Iterable[DrawLine]) -> int:
    return max((draw.seq for draw in draws), default=0) + 1


def validate_new_draw(
    quotation_total: Money,
    existing_draws: Iterable[DrawLine],
    new_amount: Money,
) -> None:
    """A new draw must be positive and must not exceed the remaining quotation amount."""
    if not new_amount.is_positive:
        raise NonPositiveAmountError(f"Draw amount must be positive, got {new_amount}")
    remaining = remaining_amount(quotation_total, existing_draws)
    if new_amount > remaining:
        raise DrawExceedsRemainingError(
            f"Draw of {new_amount} exceeds the remaining {remaining} on this quotation"
        )


def validate_payment(status: DrawStatus) -> None:
    """Only pending draws can be paid; paying twice is a rule violation."""
    if status is DrawStatus.PAID:
        raise DrawNotPayableError("Draw is already paid; paid draws are immutable")
    if status is DrawStatus.CANCELLED:
        raise DrawNotPayableError("Cancelled draws cannot be paid")


def ensure_mutable(status: DrawStatus) -> None:
    """Guard for any edit/cancel operation on a draw."""
    if status is DrawStatus.PAID:
        raise PaidDrawImmutableError("Paid draws are immutable")
