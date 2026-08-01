"""M7 Phase 2: booking analytics use case (window selection + delegation)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.booking_analytics import BookingAnalyticsUseCases
from src.domain.revenue import Stay


class FakeAnalyticsRepo:
    def __init__(self, stays: list[Stay]) -> None:
        self._stays = stays
        self.window: tuple[date, date] | None = None

    async def stays_in_window(self, window_start: date, window_end: date) -> list[Stay]:
        self.window = (window_start, window_end)
        return list(self._stays)


async def test_occupancy_last_days_builds_trailing_window_and_computes() -> None:
    stays = [Stay(date(2026, 8, 10), date(2026, 8, 14), Decimal("400"), "THB")]
    repo = FakeAnalyticsRepo(stays)
    summary = await BookingAnalyticsUseCases(repo).occupancy_last_days(
        30, today=date(2026, 8, 31), units=1, currency="THB"
    )
    assert repo.window == (date(2026, 8, 1), date(2026, 8, 31))
    assert summary.nights_sold == 4
    assert summary.occupancy_pct == Decimal("13.3")
    assert summary.adr == Decimal("100.00")


async def test_explicit_window_passthrough() -> None:
    repo = FakeAnalyticsRepo([])
    summary = await BookingAnalyticsUseCases(repo).occupancy(
        window_start=date(2026, 9, 1), window_end=date(2026, 9, 8), units=2, currency="THB"
    )
    assert repo.window == (date(2026, 9, 1), date(2026, 9, 8))
    assert summary.available_nights == 14  # 7 nights × 2 units
    assert summary.occupancy_pct == Decimal("0.0")
