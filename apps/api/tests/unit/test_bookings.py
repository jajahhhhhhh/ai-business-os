"""M7 booking ingestion: idempotent upsert over a fake collector + repo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.application.bookings import BookingIngestionUseCases, CollectedBooking


class FakeCollector:
    def __init__(self, items: list[CollectedBooking]) -> None:
        self._items = items

    async def fetch(self) -> list[CollectedBooking]:
        return list(self._items)


class FakeBookingRepo:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], CollectedBooking] = {}

    async def upsert(self, booking: CollectedBooking) -> tuple[bool, bool]:
        key = (booking.provider, booking.external_id)
        previous = self.store.get(key)
        self.store[key] = booking
        if previous is None:
            return True, False
        return False, previous != booking


class FakeAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def write(self, actor, action, entity, entity_id, diff) -> None:  # noqa: ANN001
        self.calls.append((action, diff))


def _cb(external_id: str, status: str = "booked") -> CollectedBooking:
    return CollectedBooking(
        provider="smoobu",
        external_id=external_id,
        status=status,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        gross_amount=Decimal("400"),
        currency="THB",
    )


async def test_sync_creates_updates_and_skips_unchanged() -> None:
    repo, audit = FakeBookingRepo(), FakeAudit()
    use_cases = BookingIngestionUseCases(repo, audit)

    first = await use_cases.sync(FakeCollector([_cb("1"), _cb("2")]), actor="worker")
    assert (first.fetched, first.created, first.updated, first.unchanged) == (2, 2, 0, 0)

    again = await use_cases.sync(FakeCollector([_cb("1"), _cb("2")]), actor="worker")
    assert (again.created, again.updated, again.unchanged) == (0, 0, 2)

    # #1 flips to cancelled (an update + a cancellation), #2 is unchanged.
    third = await use_cases.sync(
        FakeCollector([_cb("1", status="cancelled"), _cb("2")]), actor="worker"
    )
    assert (third.created, third.updated, third.unchanged, third.cancelled) == (0, 1, 1, 1)
    assert audit.calls[-1][0] == "bookings.synced"
