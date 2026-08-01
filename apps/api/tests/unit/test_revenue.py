"""M7 occupancy/pricing analytics: occupancy %, ADR, RevPAR (pure, no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.domain.revenue import (
    OCCUPANCY_HEADER_TH,
    STATUS_CANCELLED,
    Stay,
    format_occupancy_th,
    occupancy_summary,
)

W1 = date(2026, 8, 1)
W2 = date(2026, 8, 31)  # 30-night window [W1, W2)


def _stay(
    ci: str, co: str, amount: str | None, currency: str = "THB", status: str = "booked"
) -> Stay:
    return Stay(
        check_in=date.fromisoformat(ci),
        check_out=date.fromisoformat(co),
        gross_amount=Decimal(amount) if amount is not None else None,
        currency=currency,
        status=status,
    )


def test_basic_occupancy_adr_revpar() -> None:
    s = occupancy_summary(
        [_stay("2026-08-10", "2026-08-14", "400")], window_start=W1, window_end=W2
    )
    assert s.available_nights == 30
    assert s.nights_sold == 4
    assert s.gross_revenue == Decimal("400.00")
    assert s.adr == Decimal("100.00")  # 400 / 4
    assert s.occupancy_pct == Decimal("13.3")  # 4/30
    assert s.revpar == Decimal("13.33")  # 400 / 30


def test_straddling_stay_is_clipped_and_revenue_prorated() -> None:
    # 4-night stay, only 2 nights (Aug 1–2) fall inside the window.
    s = occupancy_summary(
        [_stay("2026-07-30", "2026-08-03", "400")], window_start=W1, window_end=W2
    )
    assert s.nights_sold == 2
    assert s.gross_revenue == Decimal("200.00")  # 400 × 2/4


def test_cancelled_stays_excluded() -> None:
    s = occupancy_summary(
        [_stay("2026-08-10", "2026-08-14", "400", status=STATUS_CANCELLED)],
        window_start=W1,
        window_end=W2,
    )
    assert s.nights_sold == 0
    assert s.gross_revenue == Decimal("0.00")
    assert s.adr == Decimal("0.00")


def test_other_currency_skipped_and_counted() -> None:
    s = occupancy_summary(
        [_stay("2026-08-10", "2026-08-14", "400", currency="EUR")],
        window_start=W1,
        window_end=W2,
        currency="THB",
    )
    assert s.nights_sold == 0
    assert s.skipped_other_currency == 1


def test_units_scale_available_nights() -> None:
    s = occupancy_summary([], window_start=W1, window_end=W2, units=3)
    assert s.available_nights == 90
    assert s.occupancy_pct == Decimal("0.0")
    assert s.adr == Decimal("0.00")


def test_occupancy_capped_at_100_on_overlap() -> None:
    full = _stay("2026-08-01", "2026-08-31", "3000")
    s = occupancy_summary([full, full], window_start=W1, window_end=W2, units=1)
    assert s.occupancy_pct == Decimal("100.0")  # 60 nights sold / 30 available, capped


def test_amount_none_counts_nights_but_no_revenue() -> None:
    s = occupancy_summary([_stay("2026-08-10", "2026-08-14", None)], window_start=W1, window_end=W2)
    assert s.nights_sold == 4
    assert s.gross_revenue == Decimal("0.00")
    assert s.adr == Decimal("0.00")


def test_invalid_window_and_units_raise() -> None:
    with pytest.raises(ValueError):
        occupancy_summary([], window_start=W2, window_end=W1)
    with pytest.raises(ValueError):
        occupancy_summary([], window_start=W1, window_end=W2, units=0)


def test_format_occupancy_th_has_header_and_metrics() -> None:
    summary = occupancy_summary(
        [_stay("2026-08-10", "2026-08-14", "400")], window_start=W1, window_end=W2
    )
    text = format_occupancy_th(summary)
    assert OCCUPANCY_HEADER_TH in text
    assert "13.3%" in text
    assert "ADR: 100.00 THB" in text
    assert "RevPAR: 13.33 THB" in text
