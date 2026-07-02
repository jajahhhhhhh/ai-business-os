"""Money value-object rules: Decimal-only, quantized, currency-safe."""

from decimal import Decimal

import pytest

from src.domain.errors import CurrencyMismatchError
from src.domain.money import Money


def test_constructs_from_decimal_and_quantizes_to_cents() -> None:
    assert Money(Decimal("10")).amount == Decimal("10.00")
    assert Money(Decimal("10.005")).amount == Decimal("10.01")  # ROUND_HALF_UP
    assert Money(Decimal("10.004")).amount == Decimal("10.00")


def test_of_accepts_int_and_str() -> None:
    assert Money.of(150000).amount == Decimal("150000.00")
    assert Money.of("99.99").amount == Decimal("99.99")


def test_rejects_float_everywhere() -> None:
    with pytest.raises(TypeError):
        Money(10.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.of(10.5)  # type: ignore[arg-type]


def test_of_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        Money.of("not-a-number")


def test_default_currency_is_thb() -> None:
    assert Money(Decimal("1")).currency == "THB"


def test_addition_and_subtraction() -> None:
    a = Money(Decimal("100.50"))
    b = Money(Decimal("0.50"))
    assert a + b == Money(Decimal("101.00"))
    assert a - b == Money(Decimal("100.00"))


def test_comparisons() -> None:
    assert Money(Decimal("1")) < Money(Decimal("2"))
    assert Money(Decimal("2")) >= Money(Decimal("2"))
    assert Money(Decimal("3")).is_positive
    assert Money.zero().is_zero
    assert not Money(Decimal("-1")).is_positive


def test_currency_mismatch_raises() -> None:
    thb = Money(Decimal("1"), "THB")
    usd = Money(Decimal("1"), "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = thb + usd
    with pytest.raises(CurrencyMismatchError):
        _ = thb < usd


def test_equality_and_immutability() -> None:
    m = Money(Decimal("5"))
    assert m == Money(Decimal("5.00"))
    with pytest.raises(AttributeError):
        m.amount = Decimal("6")  # type: ignore[misc]
