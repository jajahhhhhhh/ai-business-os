"""Marketing agents pure logic (M6): brand guide, SEO brief + content draft
composition, and the deterministic 4-week content calendar scheduler.

LLM-free and orchestrator-free so every fallback is unit-testable anywhere.
Per §3 of the architecture the OWNER-facing wrapper is Thai but the marketing
CONTENT itself is English; the SEO brief and content draft are therefore
composed in English, while the social calendar the owner reviews is Thai with
English content titles.

The three agents form a pipeline over the reports table:
    seo (kind='seo') -> content (kind='content') -> social (kind='content-calendar')
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.application.agents.ports import ReportRef, SeoInputs

# --------------------------------------------------------------- brand guide

BRAND_NAME = "How to Niksen"
BRAND_SITE = "howtoniksen.com"
BRAND_LOCATION = "Koh Samui"
# The Dutch art of doing nothing — the brand's whole promise.
BRAND_TONE = (
    "calm, unhurried, understated — the restorative art of doing nothing (niksen); "
    "sensory and specific, never salesy or superlative-heavy"
)

# Evergreen keyword themes for a boutique private-pool villa on Koh Samui.
# The SEO agent seeds its brief from these and layers competitor gaps on top.
KEYWORD_THEMES: tuple[str, ...] = (
    "private pool villa koh samui",
    "boutique villa koh samui",
    "wellness retreat koh samui",
    "slow travel koh samui",
    "quiet luxury villa thailand",
)

# Brand publishing channels (guide metadata). The calendar cadence itself is
# WEEKLY_SLOTS below; Newsletter is drafted ad hoc rather than slotted weekly.
CHANNELS: tuple[str, ...] = ("Instagram", "Facebook", "Blog", "Newsletter")

# --------------------------------------------------------------- report headers

SEO_HEADER = "SEO Content Brief"
CONTENT_HEADER = "Content Draft"
THAI_SUMMARY_HEADER = "สรุปภาษาไทย"
CALENDAR_HEADER_TH = "ปฏิทินคอนเทนต์ 4 สัปดาห์"
NO_DRAFTS_LINE_TH = "ยังไม่มีดราฟต์คอนเทนต์ให้จัดลงปฏิทิน — รันเอเจนต์ content ก่อน"

MAX_GAPS_SHOWN = 5  # competitor content-gaps fed to the brief
MAX_BRIEFS_SHOWN = 3  # SEO briefs fed to the content agent

# 4-week calendar, one post per slot; slots cycle through CHANNELS by weekday.
CALENDAR_WEEKS = 4
WEEKLY_SLOTS: tuple[tuple[str, str], ...] = (
    ("Mon", "Instagram"),
    ("Wed", "Facebook"),
    ("Fri", "Blog"),
)


# --------------------------------------------------------------------- SEO


def format_seo_inputs(inputs: SeoInputs) -> str:
    """Render SEO inputs as English bullet lines for the brief prompt."""
    lines = ["Keyword themes:"]
    lines.extend(f"- {theme}" for theme in inputs.keyword_themes or KEYWORD_THEMES)
    if inputs.content_gaps:
        lines.append("Competitor content moves worth answering:")
        for gap in inputs.content_gaps[:MAX_GAPS_SHOWN]:
            lines.append(f"- {gap.competitor_name} [{gap.category}]: {gap.summary}")
    else:
        lines.append("Competitor content moves worth answering: none flagged this period.")
    return "\n".join(lines)


def compose_seo_brief_fallback(period: str, inputs: SeoInputs) -> str:
    """Deterministic English SEO brief when the LLM is unavailable."""
    themes = inputs.keyword_themes or KEYWORD_THEMES
    lines = [
        f"{SEO_HEADER} — {period}",
        f"Site: {BRAND_SITE} ({BRAND_NAME}, {BRAND_LOCATION})",
        "",
        "Target keywords:",
    ]
    lines.extend(f"- {theme}" for theme in themes)
    lines.append("")
    lines.append("Suggested pieces:")
    for theme in themes[:MAX_BRIEFS_SHOWN]:
        lines.append(
            f'- Guide: "{theme.title()}" — 800-1200 words, ' "one primary + two supporting keywords"
        )
    if inputs.content_gaps:
        lines.append("")
        lines.append("React to competitor moves:")
        for gap in inputs.content_gaps[:MAX_GAPS_SHOWN]:
            lines.append(f"- {gap.competitor_name} [{gap.category}]: {gap.summary}")
    return "\n".join(lines)


# --------------------------------------------------------------- content draft


def _first_line(body: str, *, strip_headers: tuple[str, ...] = ()) -> str:
    """First non-empty, non-header line of a report body (used as a title)."""
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(line.startswith(header) for header in strip_headers):
            continue
        return line
    return ""


def _first_keyword(brief_body: str) -> str:
    """First target keyword from an SEO brief, else the top brand theme.

    The brief lists keywords as '- <kw>' bullets under a 'Target keywords:'
    label (see compose_seo_brief_fallback / the seo_brief prompt). Pick that
    keyword so the content title is a real topic — NOT the brief's 'Site:'
    metadata line, which the old first-non-header-line heuristic grabbed."""
    bullets: list[str] = []
    in_keywords = False
    for raw in brief_body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("target keyword"):
            in_keywords = True
            continue
        if line.startswith("-"):
            keyword = line.lstrip("-").strip()
            if in_keywords:
                return keyword
            bullets.append(keyword)
        elif in_keywords:  # left the keyword block without an earlier return
            in_keywords = False
    return bullets[0] if bullets else KEYWORD_THEMES[0]


def format_briefs(briefs: list[ReportRef]) -> str:
    """Render recent SEO briefs as context for the content-draft prompt."""
    if not briefs:
        return "No SEO brief available — draft an evergreen piece for the themes below."
    blocks = []
    for brief in briefs[:MAX_BRIEFS_SHOWN]:
        blocks.append(brief.body.strip())
    return "\n\n---\n\n".join(blocks)


def compose_content_fallback(period: str, briefs: list[ReportRef]) -> str:
    """Deterministic English draft + Thai summary when the LLM is unavailable.

    A skeleton the owner can flesh out — never a fabricated finished post."""
    keyword = _first_keyword(briefs[0].body) if briefs else KEYWORD_THEMES[0]
    theme = keyword.title()
    lines = [
        f"{CONTENT_HEADER} — {period}",
        f"Working title: {theme} at {BRAND_NAME}",
        "",
        f"Angle: {BRAND_TONE}.",
        "Outline:",
        f"- Open on a single quiet moment at the villa ({BRAND_LOCATION}).",
        "- Why slow, do-nothing days restore you — the niksen idea.",
        "- Three concrete details guests can picture (pool, view, silence).",
        "- Soft call to action: check dates for a direct booking.",
        "",
        f"{THAI_SUMMARY_HEADER}",
        f'ดราฟต์คอนเทนต์ภาษาอังกฤษเรื่อง "{theme}" สำหรับ {BRAND_NAME} — รอเจ้าของตรวจก่อนเผยแพร่',
    ]
    return "\n".join(lines)


# --------------------------------------------------------------- social calendar


@dataclass(frozen=True, slots=True)
class CalendarSlot:
    week: int  # 1-based
    day: str  # weekday label, e.g. 'Mon'
    channel: str
    title: str


def _draft_title(draft: ReportRef) -> str:
    title = _first_line(draft.body, strip_headers=(CONTENT_HEADER,))
    # Content drafts put the working title on line 2 as "Working title: ...".
    for raw in draft.body.splitlines():
        line = raw.strip()
        if line.lower().startswith("working title:"):
            return line.split(":", 1)[1].strip()
    return title or "Untitled draft"


def schedule_calendar(drafts: list[ReportRef]) -> list[CalendarSlot]:
    """Spread available drafts across CALENDAR_WEEKS × WEEKLY_SLOTS, cycling
    titles when there are fewer drafts than slots. Deterministic (no clock)."""
    titles = [_draft_title(draft) for draft in drafts] or ["(placeholder — no draft yet)"]
    slots: list[CalendarSlot] = []
    index = 0
    for week in range(1, CALENDAR_WEEKS + 1):
        for day, channel in WEEKLY_SLOTS:
            slots.append(
                CalendarSlot(week=week, day=day, channel=channel, title=titles[index % len(titles)])
            )
            index += 1
    return slots


def _week_start(reference: date) -> date:
    """Monday of the week AFTER the reference date (the calendar starts next
    Monday so the owner has lead time to approve)."""
    days_ahead = 7 - reference.weekday()  # Monday=0 -> 7 days; Sunday=6 -> 1 day
    return reference + timedelta(days=days_ahead)


def compose_content_calendar(reference: date, drafts: list[ReportRef]) -> tuple[str, str]:
    """Build the Thai 4-week calendar body and its ISO period label.

    Returns (body, period). period is 'YYYY-MM-DD..YYYY-MM-DD' (the 4-week
    window). The body is LINE-friendly plain text: Thai framing, English
    content titles (content is English per §3)."""
    start = _week_start(reference)
    end = start + timedelta(days=CALENDAR_WEEKS * 7 - 1)
    period = f"{start.isoformat()}..{end.isoformat()}"
    lines = [f"{CALENDAR_HEADER_TH} ({start.isoformat()} – {end.isoformat()})"]
    if not drafts:
        lines.append(NO_DRAFTS_LINE_TH)
    for slot in schedule_calendar(drafts):
        slot_date = start + timedelta(days=(slot.week - 1) * 7 + _weekday_offset(slot.day))
        lines.append(
            f"สัปดาห์ {slot.week} · {slot_date.isoformat()} ({slot.day}) · "
            f"{slot.channel}: {slot.title}"
        )
    return "\n".join(lines), period


_WEEKDAY_OFFSETS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _weekday_offset(day: str) -> int:
    return _WEEKDAY_OFFSETS.get(day, 0)


# --------------------------------------------------------------- prompt fallbacks
# Inline fallbacks for packages/prompts/{seo,content}/*.en.j2 (locale='en':
# the marketing content is English). Required template variables noted per line.

# Variables: period, inputs (pre-rendered English input block).
SEO_BRIEF_PROMPT_FALLBACK_EN = (
    "You are the SEO lead for " + BRAND_NAME + ", a boutique private-pool villa "
    "rental on " + BRAND_LOCATION + " (" + BRAND_SITE + ").\n"
    "Current inputs:\n{{ inputs }}\n\n"
    'Write "' + SEO_HEADER + ' {{ period }}" as an English brief: 5-8 target '
    "keywords, then 3 suggested pieces (title, primary keyword, ~word count, angle).\n"
    'The first line must be exactly "' + SEO_HEADER + ' — {{ period }}".\n'
    "Plain text, no markdown."
)

# Variables: period, briefs (recent SEO brief block), tone, brand, location.
CONTENT_DRAFT_PROMPT_FALLBACK_EN = (
    "You are a copywriter for " + BRAND_NAME + " on " + BRAND_LOCATION + ".\n"
    "Brand voice: " + BRAND_TONE + ".\n"
    "SEO brief(s) to draft from:\n{{ briefs }}\n\n"
    'Write "' + CONTENT_HEADER + ' {{ period }}": one publish-ready English draft '
    "(working title, then 150-250 words), then a short Thai summary for the owner "
    'under a "' + THAI_SUMMARY_HEADER + '" heading.\n'
    'The first line must be exactly "' + CONTENT_HEADER + ' — {{ period }}".\n'
    "Plain text, no markdown."
)
