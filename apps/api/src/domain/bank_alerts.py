"""Thai bank-alert parsing (Phase A renovation, M1).

Pure text -> structured transaction extraction for the e-mail alerts Thai
banks send on account movement. No framework imports; heavily unit-tested.

Covered formats (real-world, whitespace/comma tolerant):
- KBank / K PLUS:      "เงินออกจากบัญชี X-1234 จำนวน 50,000.00 บาท"
                       "รายการหักบัญชี ... จำนวนเงิน 50,000.00 บาท"
- SCB:                 "รายการโอนเงินสำเร็จ ... จาก บัญชี xxx-x-x1234
                        จำนวนเงิน (THB) 50,000.00"
- Bangkok Bank:        "โอนเงินออกจากบัญชี ...1234 จำนวน 50,000.00 บาท"
- Incoming variants:   "เงินเข้าบัญชี", "รับโอนเงิน"
- English fallback:    "Transfer ... THB 50,000.00 from account x1234"

Thai dates ("02/07/2569 14:30") are Buddhist era; years > 2400 are converted
to the common era (year - 543). Alerts carry Thailand wall-clock time, so
parsed datetimes are pinned to UTC+7 (Thailand has no DST).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

BANGKOK_TZ = timezone(timedelta(hours=7), name="+07:00")

_BE_YEAR_THRESHOLD = 2400  # years above this are Buddhist era
_BE_OFFSET = 543

Direction = Literal["in", "out"]


@dataclass(frozen=True, slots=True)
class ParsedAlert:
    amount_thb: Decimal
    direction: Direction
    bank: str
    account_tail: str | None
    occurred_at: datetime | None


def normalize_alert_text(raw_text: str) -> str:
    """Canonical form used for dedup hashing: collapsed whitespace, stripped."""
    return " ".join(raw_text.split())


def alert_dedup_hash(raw_text: str) -> str:
    """sha256 over the normalized alert text; stable across re-forwarded copies."""
    return hashlib.sha256(normalize_alert_text(raw_text).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ keyword tables

# Non-transaction mail is rejected outright: OTP codes, marketing, balance checks.
_REJECT_PATTERNS = (
    re.compile(r"\bOTP\b", re.IGNORECASE),
    re.compile(r"รหัส\s*(?:OTP|ผ่าน|ยืนยัน)", re.IGNORECASE),
    re.compile(r"โปรโมชั่น|โปรโมชัน"),
    re.compile(r"เช็[คก]ยอด|สอบถามยอด"),
    re.compile(r"verification\s+code", re.IGNORECASE),
)

_IN_PATTERNS = (
    re.compile(r"เงินเข้าบัญชี"),
    re.compile(r"รับโอนเงิน|รับเงินโอน"),
    re.compile(r"ฝากเงิน(?:เข้า)?บัญชี"),
    re.compile(
        r"(?:deposit|received|credited)(?:\s+\w+){0,3}\s+(?:in)?to\s+account", re.IGNORECASE
    ),
    re.compile(r"\bmoney\s+received\b", re.IGNORECASE),
)

_OUT_PATTERNS = (
    re.compile(r"เงินออกจากบัญชี"),
    re.compile(r"(?:รายการ)?หักบัญชี|หักเงินจากบัญชี"),
    re.compile(r"โอนเงินออก"),
    re.compile(r"รายการโอนเงิน"),  # SCB "รายการโอนเงินสำเร็จ ... จาก บัญชี" (outgoing)
    re.compile(r"ถอนเงิน"),
    re.compile(
        r"(?:transfer|withdrawal|debit|paid)(?:\s+\S+){0,6}\s+from\s+account", re.IGNORECASE
    ),
)

# bank keyword -> normalized short name (order matters only for readability;
# the keywords do not overlap).
_BANK_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("kasikorn", "kbank"),
    ("kbank", "kbank"),
    ("k plus", "kbank"),
    ("k+", "kbank"),
    ("กสิกร", "kbank"),
    ("ไทยพาณิชย์", "scb"),
    ("scb", "scb"),
    ("siam commercial", "scb"),
    ("bangkok bank", "bbl"),
    ("bualuang", "bbl"),
    ("ธนาคารกรุงเทพ", "bbl"),
    ("กรุงเทพ", "bbl"),
    ("krungsri", "krungsri"),
    ("กรุงศรี", "krungsri"),
    ("ayudhya", "krungsri"),
    ("krungthai", "ktb"),
    ("krung thai", "ktb"),
    ("ktb", "ktb"),
    ("กรุงไทย", "ktb"),
)

# ------------------------------------------------------------------ field regexes

_NUMBER = r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

# Priority order: an explicit amount label wins over a bare "<number> บาท",
# so account fragments and balance lines are never mistaken for the amount.
_AMOUNT_PATTERNS = (
    re.compile(rf"จำนวน(?:เงิน)?\s*(?:\(\s*THB\s*\)\s*)?:?\s*({_NUMBER})"),
    re.compile(rf"(?:THB|฿)\s*({_NUMBER})", re.IGNORECASE),
    re.compile(rf"(?:amount)\s*:?\s*({_NUMBER})", re.IGNORECASE),
    re.compile(rf"({_NUMBER})\s*(?:บาท|THB)", re.IGNORECASE),
)

# Account token right after บัญชี/account: masked digits like X-1234,
# xxx-x-x1234, ...1234, x1234. Must end in a digit.
_ACCOUNT_PATTERN = re.compile(
    r"(?:บัญชี|account)\s*(?:เลขที่\s*|no\.?\s*|number\s*)?([0-9xX*.\-…]*[0-9])"
)

_DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def _detect_direction(text: str) -> Direction | None:
    for pattern in _IN_PATTERNS:
        if pattern.search(text):
            return "in"
    for pattern in _OUT_PATTERNS:
        if pattern.search(text):
            return "out"
    return None


def _detect_bank(text: str) -> str:
    lowered = text.lower()
    for keyword, short_name in _BANK_KEYWORDS:
        if keyword in lowered:
            return short_name
    return "unknown"


def _extract_amount(text: str) -> Decimal | None:
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                amount = Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:  # pragma: no cover - regex guarantees shape
                continue
            if amount > 0:
                return amount.quantize(Decimal("0.01"))
    return None


def _extract_account_tail(text: str) -> str | None:
    match = _ACCOUNT_PATTERN.search(text)
    if match is None:
        return None
    digits = re.findall(r"\d", match.group(1))
    if not digits:
        return None
    return "".join(digits[-4:])


def _extract_occurred_at(text: str) -> datetime | None:
    match = _DATE_PATTERN.search(text)
    if match is None:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year > _BE_YEAR_THRESHOLD:  # Buddhist era -> common era
        year -= _BE_OFFSET
    hour = int(match.group(4)) if match.group(4) else 0
    minute = int(match.group(5)) if match.group(5) else 0
    second = int(match.group(6)) if match.group(6) else 0
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=BANGKOK_TZ)
    except ValueError:
        return None


def parse_alert(raw_text: str) -> ParsedAlert | None:
    """Parse a bank-alert e-mail body; None means "not a transaction alert"."""
    text = normalize_alert_text(raw_text)
    if not text:
        return None
    for pattern in _REJECT_PATTERNS:
        if pattern.search(text):
            return None
    direction = _detect_direction(text)
    if direction is None:
        return None
    amount = _extract_amount(text)
    if amount is None:
        return None
    return ParsedAlert(
        amount_thb=amount,
        direction=direction,
        bank=_detect_bank(text),
        account_tail=_extract_account_tail(text),
        occurred_at=_extract_occurred_at(text),
    )
