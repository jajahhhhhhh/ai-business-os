"""M6 marketing pure logic: SEO brief + content draft fallbacks and the
deterministic 4-week content calendar scheduler (no LLM, no orchestrator)."""

from __future__ import annotations

from datetime import date

from src.application.agents.marketing import (
    BRAND_NAME,
    CALENDAR_HEADER_TH,
    CALENDAR_WEEKS,
    CONTENT_HEADER,
    KEYWORD_THEMES,
    NO_DRAFTS_LINE_TH,
    SEO_HEADER,
    THAI_SUMMARY_HEADER,
    WEEKLY_SLOTS,
    _draft_title,
    _first_keyword,
    _week_start,
    compose_content_calendar,
    compose_content_fallback,
    compose_seo_brief_fallback,
    format_briefs,
    format_seo_inputs,
    schedule_calendar,
)
from src.application.agents.ports import ContentGap, SeoInputs
from tests.fakes import make_report_ref

GAP = ContentGap(competitor_name="Villa B", summary="new wellness package", category="promo")


# --------------------------------------------------------------------- SEO


def test_format_seo_inputs_falls_back_to_default_themes() -> None:
    rendered = format_seo_inputs(SeoInputs())
    for theme in KEYWORD_THEMES:
        assert theme in rendered
    assert "none flagged" in rendered  # no gaps


def test_format_seo_inputs_lists_content_gaps() -> None:
    rendered = format_seo_inputs(SeoInputs(content_gaps=(GAP,)))
    assert "Villa B [promo]: new wellness package" in rendered


def test_seo_fallback_brief_has_header_keywords_and_gaps() -> None:
    body = compose_seo_brief_fallback("2026-W30", SeoInputs(content_gaps=(GAP,)))
    assert body.startswith(f"{SEO_HEADER} — 2026-W30")
    assert KEYWORD_THEMES[0] in body
    assert "Villa B" in body


# ------------------------------------------------------------------ content


def test_content_fallback_has_header_and_thai_summary() -> None:
    brief = make_report_ref(f"{SEO_HEADER} — 2026-W30\nprivate pool villa koh samui")
    body = compose_content_fallback("2026-W30", [brief])
    assert body.startswith(f"{CONTENT_HEADER} — 2026-W30")
    assert THAI_SUMMARY_HEADER in body
    assert BRAND_NAME in body


def test_format_briefs_without_input_is_safe() -> None:
    assert "No SEO brief" in format_briefs([])


REALISTIC_BRIEF = (
    f"{SEO_HEADER} — 2026-W30\n"
    "Site: howtoniksen.com (How to Niksen, Koh Samui)\n\n"
    "Target keywords:\n"
    "- private pool villa koh samui\n"
    "- boutique villa koh samui\n"
)


def test_first_keyword_picks_the_keyword_not_metadata() -> None:
    assert _first_keyword(REALISTIC_BRIEF) == "private pool villa koh samui"


def test_first_keyword_falls_back_to_theme_without_keyword_section() -> None:
    assert _first_keyword(f"{SEO_HEADER} — 2026-W30\nSite: x") == KEYWORD_THEMES[0]


def test_content_fallback_title_is_a_keyword_not_brief_metadata() -> None:
    # Regression: the fallback used to grab the brief's "Site:" line as the
    # working title (howtoniksen.com …), which then propagated into the calendar.
    brief = make_report_ref(REALISTIC_BRIEF)
    body = compose_content_fallback("2026-W30", [brief])
    title_line = body.splitlines()[1]
    assert title_line == "Working title: Private Pool Villa Koh Samui at How to Niksen"
    assert "Site:" not in title_line and "howtoniksen.com" not in body


# ------------------------------------------------------------ social calendar


def test_draft_title_prefers_working_title_line() -> None:
    draft = make_report_ref(
        f"{CONTENT_HEADER} — 2026-W30\nWorking title: Quiet Mornings at the Villa\nbody..."
    )
    assert _draft_title(draft) == "Quiet Mornings at the Villa"


def test_week_start_is_always_the_following_monday() -> None:
    # 2026-07-20 is a Monday; the calendar starts the NEXT Monday (lead time).
    start = _week_start(date(2026, 7, 20))
    assert start == date(2026, 7, 27)
    assert start.weekday() == 0


def test_schedule_calendar_fills_every_slot_and_cycles_titles() -> None:
    drafts = [
        make_report_ref(f"{CONTENT_HEADER} — x\nWorking title: A"),
        make_report_ref(f"{CONTENT_HEADER} — x\nWorking title: B"),
    ]
    slots = schedule_calendar(drafts)
    assert len(slots) == CALENDAR_WEEKS * len(WEEKLY_SLOTS)
    assert {s.week for s in slots} == set(range(1, CALENDAR_WEEKS + 1))
    assert [s.channel for s in slots[:3]] == ["Instagram", "Facebook", "Blog"]
    assert {s.title for s in slots} == {"A", "B"}  # titles cycle


def test_content_calendar_body_and_period() -> None:
    draft = make_report_ref(f"{CONTENT_HEADER} — x\nWorking title: Slow Sundays")
    body, period = compose_content_calendar(date(2026, 7, 20), [draft])
    assert period == "2026-07-27..2026-08-23"  # 4-week window from next Monday
    assert body.startswith(CALENDAR_HEADER_TH)
    assert "Slow Sundays" in body
    assert body.count("สัปดาห์") >= CALENDAR_WEEKS  # header uses it too


def test_empty_calendar_flags_missing_drafts() -> None:
    body, _ = compose_content_calendar(date(2026, 7, 20), [])
    assert NO_DRAFTS_LINE_TH in body
