"""Pure lead-discovery signal logic (M5, §8.2/§8.3): prefilter, fallback
scorer, kind/language classification, contact parsing and dedup hashing.

Everything here is deterministic and I/O-free so the zero-LLM-spend paths
(prefilter, rule-based scoring) are exhaustively unit-testable. The LLM path
in application/lead_discovery.py records the same feature/verdict shapes so
`features_json` is comparable across model versions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

from src.domain.leads import IntentScore

EXCERPT_MAX_CHARS = 300

LEAD_KINDS = ("guest", "longstay", "b2b", "supplier")

# ---------------------------------------------------------------- prefilter
# A document is a candidate iff it mentions Samui AND carries an intent /
# accommodation / business term. Anything else is 'noise' — zero LLM spend.

_SAMUI_RE = re.compile(r"samui|สมุย", re.IGNORECASE)
_INTENT_TERM_RE = re.compile(
    r"villa|วิลล่า|pool\s*villa|ที่พัก|โรงแรม|accommodation|stay|rent|เช่า|month"
    r"|retreat|photoshoot|pool|landscap|furniture|เฟอร์นิเจอร์",
    re.IGNORECASE,
)


def is_candidate(text: str) -> bool:
    """True when the text is worth classifying (Samui + an intent term)."""
    return bool(_SAMUI_RE.search(text)) and bool(_INTENT_TERM_RE.search(text))


# ------------------------------------------------------------ rule features

_EXPLICIT_INTENT_RE = re.compile(r"looking\s+for|recommend|ตามหา|แนะนำ|จองที่ไหน", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    r"|\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?"
    r"|มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม"
    r"|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|เดือนหน้า|next\s+month|this\s+month",
    re.IGNORECASE,
)
_BUDGET_RE = re.compile(r"budget|฿|\bbaht\b|บาท|\bthb\b|[$€£]|งบ", re.IGNORECASE)
_GROUP_RE = re.compile(r"\b\d+\s*(?:people|pax|guests?|adults?|persons?)\b|\d+\s*คน", re.IGNORECASE)
_THAI_CHAR_RE = re.compile(r"[฀-๿]")
_LATIN_CHAR_RE = re.compile(r"[a-zA-Z]")

# Kind keywords, checked in precedence order b2b -> supplier -> longstay;
# everything else is a guest (the dominant lead type, §8.2).
_B2B_RE = re.compile(
    r"retreat|photoshoot|photographer|photo\s*shoot|production|workshop|yoga"
    r"|wellness|wedding|event\s+planner|relocation\s+agent|รีทรีต|ช่างภาพ|ถ่ายแบบ",
    re.IGNORECASE,
)
_SUPPLIER_RE = re.compile(
    r"landscap|furniture|เฟอร์นิเจอร์|supplier|ซัพพลายเออร์|รับเหมา|ผู้รับเหมา"
    r"|pool\s+(?:builder|contractor|service|maintenance)|renovat",
    re.IGNORECASE,
)
_LONGSTAY_RE = re.compile(
    r"\bmonthly\b|per\s+month|a\s+month\b|month-to-month|nomad|long[\s-]?term"
    r"|long[\s-]?stay|รายเดือน|เดือนละ|อยู่ยาว",
    re.IGNORECASE,
)

RECENT_24H_POINTS = 20
RECENT_72H_POINTS = 10
EXPLICIT_INTENT_POINTS = 25
DATES_POINTS = 15
BUDGET_POINTS = 10
GROUP_SIZE_POINTS = 5
LANGUAGE_POINTS = 5


def detect_language(text: str) -> str:
    """'th' when Thai script is present, 'en' for Latin text, '' otherwise."""
    if _THAI_CHAR_RE.search(text):
        return "th"
    if _LATIN_CHAR_RE.search(text):
        return "en"
    return ""


def classify_kind(text: str) -> str:
    if _B2B_RE.search(text):
        return "b2b"
    if _SUPPLIER_RE.search(text):
        return "supplier"
    if _LONGSTAY_RE.search(text):
        return "longstay"
    return "guest"


def score_signals(
    text: str, *, fetched_at: datetime, now: datetime
) -> tuple[int, dict[str, object]]:
    """Deterministic §8.3 fallback scorer -> (score 0-100, features_json).

    Features record the points contributed per signal so score explanations
    stay auditable on the dashboard.
    """
    age = now - fetched_at
    if age < timedelta(hours=24):
        recency = RECENT_24H_POINTS
    elif age < timedelta(hours=72):
        recency = RECENT_72H_POINTS
    else:
        recency = 0
    explicit = EXPLICIT_INTENT_POINTS if _EXPLICIT_INTENT_RE.search(text) else 0
    dates = DATES_POINTS if _DATE_RE.search(text) else 0
    budget = BUDGET_POINTS if _BUDGET_RE.search(text) else 0
    group = GROUP_SIZE_POINTS if _GROUP_RE.search(text) else 0
    language = detect_language(text)
    lang_match = LANGUAGE_POINTS if language in ("th", "en") else 0

    score = IntentScore.clamped(recency + explicit + dates + budget + group + lang_match).value
    features: dict[str, object] = {
        "recency": recency,
        "explicit_intent": explicit,
        "dates": dates,
        "budget": budget,
        "group_size": group,
        "language_match": lang_match,
        "language": language,
        "kind": classify_kind(text),
    }
    return score, features


# -------------------------------------------------------- contact & dedup

_REDDIT_HANDLE_RE = re.compile(r"^u/[A-Za-z0-9_-]{1,40}$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class LeadContact:
    """PDPA-minimized public contact (§8.5): platform + public handle only."""

    platform: str
    handle: str


def parse_contact(content: str, url: str, source_type: str) -> LeadContact:
    """Extract the public handle from a collected document.

    Reddit collector content leads with 'u/{author}' (collectors/reddit.py);
    other source types fall back to the document's host as an attributable —
    but non-personal — handle.
    """
    first_line = content.split("\n", 1)[0].strip()
    if _REDDIT_HANDLE_RE.fullmatch(first_line):
        return LeadContact(platform="reddit", handle=first_line)
    host = urlparse(url).hostname or "unknown"
    return LeadContact(platform=source_type, handle=host)


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def lead_dedup_hash(platform: str, handle: str, text: str) -> str:
    """sha256 over platform + handle + whitespace/case-normalized text."""
    payload = f"{platform}\n{handle}\n{normalize_text(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def excerpt(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    """Whitespace-collapsed excerpt capped at `limit` chars (event payloads)."""
    return _WHITESPACE_RE.sub(" ", text).strip()[:limit]
