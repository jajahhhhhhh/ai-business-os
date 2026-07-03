"""Rule-based change classification: the fallback when no LLM is available.

Keyword lists cover Thai and English because competitor sites on Samui mix
both. Severities: low|medium|high|critical — 'critical' is reserved for LLM
judgment and never produced here.
"""

from __future__ import annotations

from src.domain.diffing import TextDiff

PRICING_KEYWORDS: tuple[str, ...] = (
    "ราคา",
    "บาท",
    "฿",
    "price",
    "promotion",
    "โปรโม",
    "ส่วนลด",
    "discount",
    "%",
    "sale",
    "offer",
)

AVAILABILITY_KEYWORDS: tuple[str, ...] = (
    "จอง",
    "ห้องว่าง",
    "ว่าง",
    "ปฏิทิน",
    "เช็คอิน",
    "book",
    "booking",
    "availability",
    "available",
    "vacancy",
    "check-in",
    "calendar",
)

MAJOR_CHANGE_RATIO = 0.5


def _any_keyword(lines: tuple[str, ...], keywords: tuple[str, ...]) -> bool:
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return True
    return False


def classify_change(diff: TextDiff) -> tuple[str, str]:
    """Return (category, severity) for a diff without LLM help."""
    changed_lines = diff.added + diff.removed
    if _any_keyword(changed_lines, PRICING_KEYWORDS):
        return ("pricing", "high")
    if _any_keyword(changed_lines, AVAILABILITY_KEYWORDS):
        return ("availability", "medium")
    if diff.change_ratio >= MAJOR_CHANGE_RATIO:
        return ("content", "medium")
    return ("content", "low")
