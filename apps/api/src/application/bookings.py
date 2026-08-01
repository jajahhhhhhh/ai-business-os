"""Booking ingestion (M7): pull reservations from a PMS into the OS.

Provider-agnostic. A BookingCollector (Smoobu/Lodgify adapter in
infrastructure/pms.py) yields normalized CollectedBooking rows; the use case
upserts them by (provider, external_id) so repeated syncs are idempotent —
new reservations create, changed ones (dates/amount/status, e.g. a
cancellation) update, unchanged ones are skipped. No guest PII is carried:
analytics only need dates, amount, status and channel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import structlog

from src.application.repositories import AuditWriter

logger = structlog.get_logger("application.bookings")

STATUS_BOOKED = "booked"
STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CollectedBooking:
    """A reservation normalized from a PMS payload (no guest PII)."""

    provider: str  # smoobu|lodgify
    external_id: str  # the PMS's reservation id
    status: str  # booked|cancelled
    check_in: date
    check_out: date
    gross_amount: Decimal | None
    currency: str
    channel: str | None = None  # airbnb|booking|direct|…
    property_ref: str | None = None
    guests: int | None = None


class BookingCollector(Protocol):
    async def fetch(self) -> list[CollectedBooking]:
        """Return all reservations the PMS exposes for the account."""
        ...


class BookingRepository(Protocol):
    async def upsert(self, booking: CollectedBooking) -> tuple[bool, bool]:
        """Insert or update by (provider, external_id).

        Returns (created, changed): created=True on insert; on an existing row
        changed=True iff any analytics-relevant field differed."""
        ...


@dataclass
class IngestionStats:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    cancelled: int = 0  # cancellations seen in this batch (subset of the above)

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class BookingIngestionUseCases:
    """Sync a PMS account's reservations into the bookings table."""

    def __init__(self, repository: BookingRepository, audit: AuditWriter) -> None:
        self._repo = repository
        self._audit = audit

    async def sync(self, collector: BookingCollector, *, actor: str) -> IngestionStats:
        bookings = await collector.fetch()
        stats = IngestionStats(fetched=len(bookings))
        for booking in bookings:
            created, changed = await self._repo.upsert(booking)
            if created:
                stats.created += 1
            elif changed:
                stats.updated += 1
            else:
                stats.unchanged += 1
            if booking.status == STATUS_CANCELLED:
                stats.cancelled += 1
        await self._audit.write(actor, "bookings.synced", "bookings", None, stats.as_dict())
        logger.info("bookings_synced", **stats.as_dict())
        return stats
