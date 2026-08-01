"""Guest comms use case (M7): send the post-checkout review request.

Scans bookings that checked out inside a trailing window and haven't been
nudged yet, composes one owner-facing LINE message, and — only if delivery
succeeds — marks them requested so each booking is nudged at most once (a LINE
outage simply retries next run). Skips cleanly when there is no review URL.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Protocol

import structlog

from src.application.repositories import AuditWriter
from src.domain.guest_comms import Checkout, compose_review_request

logger = structlog.get_logger("application.guest_comms")


@dataclass(frozen=True, slots=True)
class CheckoutRow:
    booking_id: uuid.UUID
    property_ref: str | None
    check_out: date
    channel: str | None
    nights: int


class GuestCommsRepository(Protocol):
    async def checkouts_awaiting_review(
        self, window_start: date, window_end: date
    ) -> list[CheckoutRow]:
        """Booked stays with check_out in [window_start, window_end) and no
        review request sent yet."""
        ...

    async def mark_review_requested(self, booking_ids: list[uuid.UUID], at: datetime) -> None: ...


class Notifier(Protocol):
    async def push(self, text: str) -> bool: ...


@dataclass
class GuestCommsStats:
    due: int = 0
    notified: int = 0
    line_sent: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class GuestCommsUseCases:
    def __init__(
        self,
        repository: GuestCommsRepository,
        notifier: Notifier,
        audit: AuditWriter,
        *,
        brand: str,
        review_url: str,
    ) -> None:
        self._repo = repository
        self._notifier = notifier
        self._audit = audit
        self._brand = brand
        self._review_url = review_url

    async def send_review_requests(
        self, *, window_start: date, window_end: date, now: datetime, actor: str
    ) -> GuestCommsStats:
        rows = await self._repo.checkouts_awaiting_review(window_start, window_end)
        stats = GuestCommsStats(due=len(rows))
        if not rows:
            return stats
        if not self._review_url:
            logger.info("review_request_skipped", reason="no review url", due=len(rows))
            return stats

        message = compose_review_request(
            brand=self._brand,
            review_url=self._review_url,
            checkouts=[Checkout(r.property_ref, r.check_out, r.channel, r.nights) for r in rows],
        )
        stats.line_sent = await self._notifier.push(message)
        if stats.line_sent:
            # Mark ONLY on success — a failed push retries these next run.
            await self._repo.mark_review_requested([r.booking_id for r in rows], now)
            stats.notified = len(rows)
            await self._audit.write(
                actor, "guest.review_requested", "bookings", None, {"count": len(rows)}
            )
        logger.info("review_requests_sent", **stats.as_dict())
        return stats
