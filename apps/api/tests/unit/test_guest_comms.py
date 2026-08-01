"""M7 guest comms: review-request composition + send-once use case."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from src.application.guest_comms import (
    CheckoutRow,
    GuestCommsUseCases,
)
from src.domain.guest_comms import (
    REVIEW_REQUEST_HEADER_TH,
    Checkout,
    compose_review_request,
)

REVIEW_URL = "https://g.page/r/howtoniksen/review"
BRAND = "How to Niksen"


# ------------------------------------------------------------------- domain


def test_compose_review_request_has_header_brand_link_and_checkouts() -> None:
    text = compose_review_request(
        brand=BRAND,
        review_url=REVIEW_URL,
        checkouts=[
            Checkout(
                property_ref="Villa Niksen", check_out=date(2026, 8, 5), channel="Airbnb", nights=4
            )
        ],
    )
    assert REVIEW_REQUEST_HEADER_TH in text
    assert BRAND in text
    assert REVIEW_URL in text
    assert "2026-08-05 · Villa Niksen · Airbnb · 4 คืน" in text
    assert "EN:" in text and "TH:" in text


# ---------------------------------------------------------------- use case


class FakeGuestRepo:
    def __init__(self, rows: list[CheckoutRow]) -> None:
        self._rows = rows
        self.marked: list[uuid.UUID] = []

    async def checkouts_awaiting_review(self, window_start, window_end) -> list[CheckoutRow]:
        # Mimic the SQL filter: exclude already-marked bookings.
        return [r for r in self._rows if r.booking_id not in self.marked]

    async def mark_review_requested(self, booking_ids, at) -> None:
        self.marked.extend(booking_ids)


class FakeNotifier:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.pushes: list[str] = []

    async def push(self, text: str) -> bool:
        self.pushes.append(text)
        return self.ok


class FakeAudit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def write(self, actor, action, entity, entity_id, diff) -> None:  # noqa: ANN001
        self.actions.append(action)


def _row(nights: int = 3) -> CheckoutRow:
    return CheckoutRow(
        booking_id=uuid.uuid4(),
        property_ref="Villa Niksen",
        check_out=date(2026, 8, 5),
        channel="Direct",
        nights=nights,
    )


WS, WE, NOW = date(2026, 8, 3), date(2026, 8, 6), datetime(2026, 8, 6, tzinfo=UTC)


async def _run(repo, notifier, *, review_url=REVIEW_URL):
    use_cases = GuestCommsUseCases(repo, notifier, FakeAudit(), brand=BRAND, review_url=review_url)
    return await use_cases.send_review_requests(
        window_start=WS, window_end=WE, now=NOW, actor="worker"
    )


async def test_sends_once_and_is_idempotent() -> None:
    repo = FakeGuestRepo([_row(), _row()])
    notifier = FakeNotifier(ok=True)

    first = await _run(repo, notifier)
    assert (first.due, first.notified, first.line_sent) == (2, 2, True)
    assert len(notifier.pushes) == 1  # one owner message for the batch
    assert len(repo.marked) == 2

    # Re-run: both already marked → nothing due, no second push.
    second = await _run(repo, notifier)
    assert (second.due, second.notified) == (0, 0)
    assert len(notifier.pushes) == 1


async def test_failed_push_does_not_mark_so_it_retries() -> None:
    repo = FakeGuestRepo([_row()])
    stats = await _run(repo, FakeNotifier(ok=False))
    assert stats.due == 1 and stats.notified == 0 and stats.line_sent is False
    assert repo.marked == []  # not marked → next run retries


async def test_no_review_url_skips_without_marking() -> None:
    repo = FakeGuestRepo([_row()])
    notifier = FakeNotifier(ok=True)
    stats = await _run(repo, notifier, review_url="")
    assert stats.due == 1 and stats.notified == 0
    assert notifier.pushes == [] and repo.marked == []
