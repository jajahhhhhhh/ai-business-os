"""Rule-based change classification: the deterministic fallback when the
ChangeAnalyst LLM is unavailable, over budget, or returns garbage.

Keyword rules run on the ADDED diff lines (what the competitor now says).
Lists cover Thai and English because competitor sites on Samui mix both.

Rules (spec §M3.4):
- pricing/promotion keywords (ราคา|บาท|฿|%|โปรโมชั่น|promotion|discount|sale)
  -> promotion when a promo word matched, otherwise pricing; severity high
- listing keywords (ห้องพัก|villa|room|เปิดจอง|book) -> listing, medium
- anything else -> content, medium
- more than 50% of the text changed -> severity upgraded to high

'critical' is reserved for LLM judgment and never produced here.
"""

from __future__ import annotations

from src.domain.diffing import TextDiff

PROMOTION_KEYWORDS: tuple[str, ...] = ("โปรโมชั่น", "promotion", "discount", "sale")
PRICING_KEYWORDS: tuple[str, ...] = ("ราคา", "บาท", "฿", "%")
LISTING_KEYWORDS: tuple[str, ...] = ("ห้องพัก", "villa", "room", "เปิดจอง", "book")

MAJOR_CHANGE_RATIO = 0.5

FALLBACK_SUMMARY_MAX_CHARS = 160
FALLBACK_SUMMARY_EMPTY_TH = "เนื้อหาบนหน้าเว็บเปลี่ยนไปจากเดิม"


def _matches(lines: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return True
    return False


def classify_change(diff: TextDiff) -> tuple[str, str]:
    """Return (category, severity) for a diff without LLM help."""
    added = diff.added
    if _matches(added, PROMOTION_KEYWORDS):
        category, severity = "promotion", "high"
    elif _matches(added, PRICING_KEYWORDS):
        category, severity = "pricing", "high"
    elif _matches(added, LISTING_KEYWORDS):
        category, severity = "listing", "medium"
    else:
        category, severity = "content", "medium"
    if diff.change_ratio > MAJOR_CHANGE_RATIO:
        severity = "high"
    return category, severity


def fallback_summary(diff: TextDiff) -> str:
    """Deterministic summary: the first 160 characters of the added text."""
    added_text = " ".join(" ".join(line.split()) for line in diff.added if line.strip())
    if not added_text:
        added_text = FALLBACK_SUMMARY_EMPTY_TH
    if len(added_text) > FALLBACK_SUMMARY_MAX_CHARS:
        return added_text[: FALLBACK_SUMMARY_MAX_CHARS - 1] + "…"
    return added_text
