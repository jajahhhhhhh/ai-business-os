"""M7 PMS adapters: Smoobu/Lodgify payload parsing + collector gating."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.config import Settings
from src.infrastructure.pms import (
    LodgifyCollector,
    SmoobuCollector,
    build_booking_collector,
    parse_lodgify,
    parse_smoobu,
)

SMOOBU_PAGE = {
    "page_count": 1,
    "bookings": [
        {
            "id": 101,
            "arrival": "2026-08-01",
            "departure": "2026-08-05",
            "price": 400,
            "currency": "THB",
            "channel": {"name": "Airbnb"},
            "apartment": {"id": 1, "name": "Villa Niksen"},
            "adults": 2,
            "children": 1,
        },
        {
            "id": 102,
            "arrival": "2026-08-10",
            "departure": "2026-08-12",
            "type": "cancellation",
            "price": 200,
        },
        {"id": 103, "arrival": "2026-08-20", "departure": "2026-08-25", "is-blocked-booking": True},
    ],
}

LODGIFY_PAGE = {
    "items": [
        {
            "id": 9,
            "arrival": "2026-09-01",
            "departure": "2026-09-04",
            "status": "Booked",
            "total_amount": 600,
            "currency_code": "EUR",
            "source": "Booking.com",
            "property_id": 7,
            "people": 2,
        },
        {"id": 10, "arrival": "2026-09-10", "departure": "2026-09-12", "status": "Declined"},
        {"id": 11, "status": "Tentative"},
    ],
}


def test_parse_smoobu_normalizes_and_skips_blocked() -> None:
    out = parse_smoobu(SMOOBU_PAGE, default_currency="THB")
    assert len(out) == 2  # blocked owner-hold skipped
    first = out[0]
    assert (first.provider, first.external_id, first.status) == ("smoobu", "101", "booked")
    assert first.check_in == date(2026, 8, 1) and first.check_out == date(2026, 8, 5)
    assert first.gross_amount == Decimal("400") and first.currency == "THB"
    assert first.channel == "Airbnb" and first.property_ref == "Villa Niksen" and first.guests == 3
    assert out[1].status == "cancelled" and out[1].currency == "THB"  # default applied


def test_parse_lodgify_maps_status_and_skips_tentative() -> None:
    out = parse_lodgify(LODGIFY_PAGE, default_currency="THB")
    assert len(out) == 2  # tentative skipped
    assert (out[0].external_id, out[0].status, out[0].currency) == ("9", "booked", "EUR")
    assert out[0].channel == "Booking.com" and out[0].property_ref == "7" and out[0].guests == 2
    assert out[1].status == "cancelled"


def test_build_collector_is_gated_by_config() -> None:
    assert build_booking_collector(Settings()) is None  # unconfigured → skip
    assert build_booking_collector(Settings(pms_provider="smoobu")) is None  # no key
    assert isinstance(
        build_booking_collector(Settings(pms_provider="smoobu", smoobu_api_key="k")),
        SmoobuCollector,
    )
    assert isinstance(
        build_booking_collector(Settings(pms_provider="lodgify", lodgify_api_key="k")),
        LodgifyCollector,
    )
