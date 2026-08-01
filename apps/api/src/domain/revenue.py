"""Occupancy & pricing analytics (M7): occupancy %, ADR, RevPAR from bookings.

Pure and provider-agnostic — no DB, no HTTP, no clock. Standard lodging math
over a [window_start, window_end) date range for a fixed room inventory:

    occupancy = room-nights sold / available room-nights   (capped at 100%)
    ADR       = room revenue / room-nights sold             (average daily rate)
    RevPAR    = room revenue / available room-nights        (≈ ADR × occupancy)

A stay that straddles the window is clipped to its in-window nights, and its
revenue is pro-rated by the in-window fraction, so a partial stay contributes
proportionally. Cancelled stays are excluded. Amounts stay Decimal (never
float); analytics run in a single caller-chosen currency and stays in other
currencies are skipped and counted rather than summed across FX.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

STATUS_BOOKED = "booked"
STATUS_CANCELLED = "cancelled"

_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class Stay:
    """A normalized reservation for analytics (no guest PII)."""

    check_in: date
    check_out: date
    gross_amount: Decimal | None
    currency: str
    status: str = STATUS_BOOKED


@dataclass(frozen=True, slots=True)
class OccupancySummary:
    window_start: date
    window_end: date
    currency: str
    units: int
    available_nights: int
    nights_sold: int
    gross_revenue: Decimal
    occupancy_pct: Decimal  # 0–100, 1 decimal place
    adr: Decimal  # average daily rate
    revpar: Decimal
    skipped_other_currency: int


def _overlap_nights(check_in: date, check_out: date, start: date, end: date) -> int:
    """Nights of [check_in, check_out) that fall inside [start, end)."""
    lo = max(check_in, start)
    hi = min(check_out, end)
    return max(0, (hi - lo).days)


def occupancy_summary(
    stays: list[Stay],
    *,
    window_start: date,
    window_end: date,
    units: int = 1,
    currency: str = "THB",
) -> OccupancySummary:
    """Occupancy/ADR/RevPAR over [window_start, window_end) for `units` rooms."""
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if units < 1:
        raise ValueError("units must be >= 1")

    available = (window_end - window_start).days * units
    nights_sold = 0
    revenue = Decimal("0")
    skipped = 0

    for stay in stays:
        if stay.status != STATUS_BOOKED:
            continue
        if stay.currency != currency:
            skipped += 1
            continue
        booking_nights = max(0, (stay.check_out - stay.check_in).days)
        if booking_nights == 0:
            continue
        overlap = _overlap_nights(stay.check_in, stay.check_out, window_start, window_end)
        if overlap == 0:
            continue
        nights_sold += overlap
        if stay.gross_amount is not None:
            # Pro-rate the stay's revenue by the fraction of its nights in-window.
            revenue += stay.gross_amount * Decimal(overlap) / Decimal(booking_nights)

    gross = revenue.quantize(_CENT, rounding=ROUND_HALF_UP)
    if available:
        raw_occ = Decimal(nights_sold) / Decimal(available) * 100
        occupancy = min(raw_occ, Decimal("100")).quantize(_TENTH, rounding=ROUND_HALF_UP)
        revpar = (gross / Decimal(available)).quantize(_CENT, rounding=ROUND_HALF_UP)
    else:  # unreachable given the guards, but keeps the metric total
        occupancy = Decimal("0.0")
        revpar = Decimal("0.00")
    adr = (
        (gross / Decimal(nights_sold)).quantize(_CENT, rounding=ROUND_HALF_UP)
        if nights_sold
        else Decimal("0.00")
    )

    return OccupancySummary(
        window_start=window_start,
        window_end=window_end,
        currency=currency,
        units=units,
        available_nights=available,
        nights_sold=nights_sold,
        gross_revenue=gross,
        occupancy_pct=occupancy,
        adr=adr,
        revpar=revpar,
        skipped_other_currency=skipped,
    )


OCCUPANCY_HEADER_TH = "ผลประกอบการเข้าพัก"


def format_occupancy_th(summary: OccupancySummary) -> str:
    """LINE-friendly Thai occupancy block for the weekly report (content in the
    reporting currency; numbers are the owner-facing metrics)."""
    return (
        f"{OCCUPANCY_HEADER_TH} ({summary.window_start.isoformat()} – "
        f"{summary.window_end.isoformat()})\n"
        f"- อัตราการเข้าพัก: {summary.occupancy_pct}% "
        f"({summary.nights_sold}/{summary.available_nights} คืน)\n"
        f"- ADR: {summary.adr} {summary.currency} · "
        f"RevPAR: {summary.revpar} {summary.currency}\n"
        f"- รายได้รวม: {summary.gross_revenue} {summary.currency}"
    )
