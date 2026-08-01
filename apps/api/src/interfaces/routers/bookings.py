"""Booking occupancy/pricing metrics (M7 Phase 2): the dashboard tile source."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from src.application.booking_analytics import BookingAnalyticsUseCases
from src.domain.bank_alerts import BANGKOK_TZ
from src.infrastructure.repositories import BookingSqlRepository
from src.interfaces.dependencies import SessionDep, SettingsDep
from src.interfaces.schemas import OccupancyOut

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("/occupancy", response_model=OccupancyOut)
async def occupancy(
    session: SessionDep,
    settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> OccupancyOut:
    """Occupancy %, ADR and RevPAR over the trailing `days`-day window, using
    PMS_ROOM_COUNT rooms and PMS_CURRENCY as the reporting currency."""
    today = datetime.now(BANGKOK_TZ).date()
    summary = await BookingAnalyticsUseCases(BookingSqlRepository(session)).occupancy_last_days(
        days, today=today, units=settings.pms_room_count, currency=settings.pms_currency
    )
    return OccupancyOut(
        window_start=summary.window_start,
        window_end=summary.window_end,
        currency=summary.currency,
        units=summary.units,
        available_nights=summary.available_nights,
        nights_sold=summary.nights_sold,
        gross_revenue=summary.gross_revenue,
        occupancy_pct=summary.occupancy_pct,
        adr=summary.adr,
        revpar=summary.revpar,
    )
