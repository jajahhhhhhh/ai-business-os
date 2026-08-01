"""PMS booking collectors (M7): Smoobu + Lodgify.

Two layers, kept apart so the mapping is testable without a network:
- pure `parse_smoobu` / `parse_lodgify` turn a decoded JSON page into
  normalized CollectedBooking rows (unit-tested against sample payloads);
- `SmoobuCollector` / `LodgifyCollector` do the authenticated, paginated HTTP
  fetch and delegate to the parser.

`build_booking_collector` returns the configured provider's collector, or None
when the PMS is unconfigured — the worker then skips cleanly (Gmail/Reddit
pattern), never raising. Field names follow the documented Smoobu and Lodgify
v2 APIs; validate against a live account before first production sync.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from src.application.bookings import STATUS_BOOKED, STATUS_CANCELLED, CollectedBooking
from src.config import Settings

logger = structlog.get_logger("infrastructure.pms")

PROVIDER_SMOOBU = "smoobu"
PROVIDER_LODGIFY = "lodgify"

_HTTP_TIMEOUT = 30.0
_MAX_PAGES = 50  # runaway guard for pagination


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


# --------------------------------------------------------------------- Smoobu


def parse_smoobu(payload: dict[str, Any], *, default_currency: str) -> list[CollectedBooking]:
    """Normalize one Smoobu /reservations page. Blocked owner-holds (not guest
    bookings) are skipped; type == 'cancellation' maps to cancelled."""
    out: list[CollectedBooking] = []
    for row in payload.get("bookings", []):
        if row.get("is-blocked-booking"):
            continue
        check_in = _as_date(row.get("arrival"))
        check_out = _as_date(row.get("departure"))
        external_id = row.get("id")
        if check_in is None or check_out is None or external_id is None:
            continue
        status = STATUS_CANCELLED if row.get("type") == "cancellation" else STATUS_BOOKED
        channel = row.get("channel")
        if isinstance(channel, dict):
            channel = channel.get("name")
        apartment = row.get("apartment") or {}
        guests = None
        if row.get("adults") is not None or row.get("children") is not None:
            guests = int(row.get("adults") or 0) + int(row.get("children") or 0)
        out.append(
            CollectedBooking(
                provider=PROVIDER_SMOOBU,
                external_id=str(external_id),
                status=status,
                check_in=check_in,
                check_out=check_out,
                gross_amount=_as_amount(row.get("price")),
                currency=row.get("currency") or default_currency,
                channel=channel,
                property_ref=str(apartment.get("name") or apartment.get("id") or "") or None,
                guests=guests,
            )
        )
    return out


# Lodgify status → normalized status. Only confirmed states are ingested.
_LODGIFY_STATUS = {"booked": STATUS_BOOKED, "declined": STATUS_CANCELLED}


def parse_lodgify(payload: dict[str, Any], *, default_currency: str) -> list[CollectedBooking]:
    """Normalize one Lodgify v2 /reservations/bookings page. Only Booked and
    Declined (→ cancelled) states are ingested; tentative/open are skipped."""
    out: list[CollectedBooking] = []
    for row in payload.get("items", []):
        status = _LODGIFY_STATUS.get(str(row.get("status", "")).lower())
        if status is None:
            continue
        check_in = _as_date(row.get("arrival"))
        check_out = _as_date(row.get("departure"))
        external_id = row.get("id")
        if check_in is None or check_out is None or external_id is None:
            continue
        out.append(
            CollectedBooking(
                provider=PROVIDER_LODGIFY,
                external_id=str(external_id),
                status=status,
                check_in=check_in,
                check_out=check_out,
                gross_amount=_as_amount(row.get("total_amount")),
                currency=row.get("currency_code") or default_currency,
                channel=row.get("source"),
                property_ref=(
                    str(row["property_id"]) if row.get("property_id") is not None else None
                ),
                guests=(int(row["people"]) if row.get("people") is not None else None),
            )
        )
    return out


# ------------------------------------------------------------------ collectors


class SmoobuCollector:
    BASE_URL = "https://login.smoobu.com/api"

    def __init__(
        self, api_key: str, *, default_currency: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._default_currency = default_currency
        self._client = client or httpx.AsyncClient(
            base_url=self.BASE_URL, timeout=_HTTP_TIMEOUT, headers={"Api-Key": api_key}
        )

    async def fetch(self) -> list[CollectedBooking]:
        bookings: list[CollectedBooking] = []
        page = 1
        while page <= _MAX_PAGES:
            resp = await self._client.get("/reservations", params={"page": page})
            resp.raise_for_status()
            payload = resp.json()
            bookings.extend(parse_smoobu(payload, default_currency=self._default_currency))
            if page >= int(payload.get("page_count", page)):
                break
            page += 1
        return bookings

    async def aclose(self) -> None:
        await self._client.aclose()


class LodgifyCollector:
    BASE_URL = "https://api.lodgify.com/v2"
    PAGE_SIZE = 50

    def __init__(
        self, api_key: str, *, default_currency: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._default_currency = default_currency
        self._client = client or httpx.AsyncClient(
            base_url=self.BASE_URL, timeout=_HTTP_TIMEOUT, headers={"X-ApiKey": api_key}
        )

    async def fetch(self) -> list[CollectedBooking]:
        bookings: list[CollectedBooking] = []
        page = 1
        while page <= _MAX_PAGES:
            resp = await self._client.get(
                "/reservations/bookings", params={"page": page, "size": self.PAGE_SIZE}
            )
            resp.raise_for_status()
            payload = resp.json()
            items = parse_lodgify(payload, default_currency=self._default_currency)
            bookings.extend(items)
            if len(payload.get("items", [])) < self.PAGE_SIZE:
                break
            page += 1
        return bookings

    async def aclose(self) -> None:
        await self._client.aclose()


def build_booking_collector(settings: Settings) -> SmoobuCollector | LodgifyCollector | None:
    """The configured provider's collector, or None when unconfigured (skip)."""
    provider = (settings.pms_provider or "").lower()
    if provider == PROVIDER_SMOOBU and settings.smoobu_api_key:
        return SmoobuCollector(settings.smoobu_api_key, default_currency=settings.pms_currency)
    if provider == PROVIDER_LODGIFY and settings.lodgify_api_key:
        return LodgifyCollector(settings.lodgify_api_key, default_currency=settings.pms_currency)
    logger.info("booking_collector_unconfigured", provider=provider or "(none)")
    return None
