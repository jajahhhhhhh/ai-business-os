"""Guest comms message composition (M7): the post-checkout review request.

Pure — no DB, no HTTP, no clock. Composes the owner-facing LINE nudge: which
guests just checked out plus a ready-to-send review request (EN + TH) carrying
the Google review link. No guest PII (the OS stores none); the owner forwards
the copy through whatever channel already holds the guest (PMS thread, chat).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

REVIEW_REQUEST_HEADER_TH = "ขอรีวิวจากแขกที่เพิ่งเช็คเอาต์"


@dataclass(frozen=True, slots=True)
class Checkout:
    property_ref: str | None
    check_out: date
    channel: str | None
    nights: int


def compose_review_request(*, brand: str, review_url: str, checkouts: list[Checkout]) -> str:
    """Owner LINE nudge listing recent checkouts + a copy-paste review request."""
    lines = [f"{REVIEW_REQUEST_HEADER_TH} ({len(checkouts)} รายการ)"]
    for checkout in checkouts:
        ref = checkout.property_ref or "วิลล่า"
        via = f" · {checkout.channel}" if checkout.channel else ""
        lines.append(f"- {checkout.check_out.isoformat()} · {ref}{via} · {checkout.nights} คืน")
    lines.append("")
    lines.append("ส่งข้อความนี้ให้แขกเพื่อขอรีวิว Google:")
    lines.append("")
    lines.append(
        f"EN: Thank you for staying at {brand}! If you enjoyed your slow days "
        f"with us, a short Google review helps other guests find us — {review_url}"
    )
    lines.append(
        f"TH: ขอบคุณที่มาพักกับ {brand} ค่ะ 🙏 ถ้าประทับใจ รบกวนรีวิวสั้น ๆ ใน Google "
        f"ให้หน่อยนะคะ — {review_url}"
    )
    return "\n".join(lines)
