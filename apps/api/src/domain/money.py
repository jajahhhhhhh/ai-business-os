"""Money value object. Decimal-based; floats are rejected outright."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from src.domain.errors import CurrencyMismatchError

_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount quantized to 2 decimal places.

    Default currency is THB (all Phase A renovation data is in Thai Baht).
    """

    amount: Decimal
    currency: str = "THB"

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError("Money amount must be Decimal, int, or str - never float")
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))
        object.__setattr__(self, "amount", self.amount.quantize(_CENT, rounding=ROUND_HALF_UP))

    @classmethod
    def of(cls, value: Decimal | int | str, currency: str = "THB") -> Money:
        if isinstance(value, float):
            raise TypeError("Money amount must be Decimal, int, or str - never float")
        try:
            return cls(Decimal(str(value)), currency)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid monetary amount: {value!r}") from exc

    @classmethod
    def zero(cls, currency: str = "THB") -> Money:
        return cls(Decimal("0"), currency)

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount >= other.amount

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
