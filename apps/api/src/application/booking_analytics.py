"""Booking analytics (M7 Phase 2): occupancy/ADR/RevPAR over a window.

Thin application layer over the pure domain.revenue engine — reads stays from
a BookingAnalyticsRepository and computes the summary. Surfaced by the
occupancy API endpoint (dashboard tile) and injected into the weekly report.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

from src.domain.revenue import OccupancySummary, Stay, occupancy_summary


class BookingAnalyticsRepository(Protocol):
    async def stays_in_window(self, window_start: date, window_end: date) -> list[Stay]: ...


class BookingAnalyticsUseCases:
    def __init__(self, repository: BookingAnalyticsRepository) -> None:
        self._repo = repository

    async def occupancy(
        self,
        *,
        window_start: date,
        window_end: date,
        units: int,
        currency: str,
    ) -> OccupancySummary:
        stays = await self._repo.stays_in_window(window_start, window_end)
        return occupancy_summary(
            stays,
            window_start=window_start,
            window_end=window_end,
            units=units,
            currency=currency,
        )

    async def occupancy_last_days(
        self, days: int, *, today: date, units: int, currency: str
    ) -> OccupancySummary:
        """Occupancy over the trailing `days`-day window ending today."""
        return await self.occupancy(
            window_start=today - timedelta(days=days),
            window_end=today,
            units=units,
            currency=currency,
        )
