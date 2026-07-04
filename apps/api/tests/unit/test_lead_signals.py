"""M5 pure lead-signal logic: prefilter, §8.3 fallback scorer, kind/language,
contact parsing, dedup hashing (src/domain/lead_signals.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.lead_signals import (
    classify_kind,
    detect_language,
    excerpt,
    is_candidate,
    lead_dedup_hash,
    parse_contact,
    score_signals,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
FRESH = NOW - timedelta(hours=1)
OLD = NOW - timedelta(days=10)


# ------------------------------------------------------------------ prefilter


@pytest.mark.parametrize(
    "text",
    [
        "Looking for a villa in Koh Samui in August",
        "Best pool villa on samui for rent?",
        "หาที่พักที่สมุยช่วยแนะนำหน่อยครับ",
        "อยากเช่าวิลล่าที่เกาะสมุยเดือนหน้า",
        "Retreat venue on Koh Samui for 20 people",
        "Looking for a furniture supplier in Samui",
        "Photoshoot location in koh samui, any ideas?",
        "Digital nomad monthly stay Samui",
    ],
)
def test_prefilter_accepts_samui_intent_posts(text: str) -> None:
    assert is_candidate(text)


@pytest.mark.parametrize(
    "text",
    [
        "Looking for a villa in Phuket",  # intent, no Samui
        "Best restaurants in Koh Samui",  # Samui, no intent term
        "Where do I find good ramen in Bangkok?",
        "สมุยฝนตกไหมช่วงนี้",  # Samui, weather chat only
        "Monthly rental apartment in Chiang Mai",
        "",
    ],
)
def test_prefilter_rejects_noise(text: str) -> None:
    assert not is_candidate(text)


# ------------------------------------------------------- scorer, feature by feature

BASE = "we want koh samui"  # Samui mention only: no scoring signals except language


def test_scorer_recency_under_24h_scores_20() -> None:
    score, features = score_signals(BASE, fetched_at=NOW - timedelta(hours=23), now=NOW)
    assert features["recency"] == 20
    assert score == 25  # +5 language(en)


def test_scorer_recency_under_72h_scores_10() -> None:
    _, features = score_signals(BASE, fetched_at=NOW - timedelta(hours=48), now=NOW)
    assert features["recency"] == 10


def test_scorer_recency_beyond_72h_scores_0() -> None:
    _, features = score_signals(BASE, fetched_at=NOW - timedelta(hours=100), now=NOW)
    assert features["recency"] == 0


def test_scorer_explicit_intent_english_adds_25() -> None:
    _, features = score_signals("looking for a villa koh samui", fetched_at=OLD, now=NOW)
    assert features["explicit_intent"] == 25


def test_scorer_explicit_intent_thai_adds_25() -> None:
    _, features = score_signals("ตามหาวิลล่าที่สมุย", fetched_at=OLD, now=NOW)
    assert features["explicit_intent"] == 25


def test_scorer_dates_add_15() -> None:
    _, features = score_signals("koh samui villa in August", fetched_at=OLD, now=NOW)
    assert features["dates"] == 15
    _, features_th = score_signals("ไปสมุยเดือนหน้า", fetched_at=OLD, now=NOW)
    assert features_th["dates"] == 15


def test_scorer_budget_signal_adds_10() -> None:
    _, features = score_signals("samui villa budget $1500", fetched_at=OLD, now=NOW)
    assert features["budget"] == 10
    _, features_th = score_signals("สมุย งบ 30,000 บาท", fetched_at=OLD, now=NOW)
    assert features_th["budget"] == 10


def test_scorer_group_size_adds_5() -> None:
    _, features = score_signals("samui villa for 4 people", fetched_at=OLD, now=NOW)
    assert features["group_size"] == 5
    _, features_th = score_signals("ไปสมุยกัน 4 คน", fetched_at=OLD, now=NOW)
    assert features_th["group_size"] == 5


def test_scorer_language_match_adds_5_for_thai_and_english() -> None:
    _, features_en = score_signals(BASE, fetched_at=OLD, now=NOW)
    assert features_en["language_match"] == 5 and features_en["language"] == "en"
    _, features_th = score_signals("สมุย", fetched_at=OLD, now=NOW)
    assert features_th["language_match"] == 5 and features_th["language"] == "th"
    _, features_none = score_signals("12345", fetched_at=OLD, now=NOW)
    assert features_none["language_match"] == 0


def test_scorer_all_signals_sum_and_clamp() -> None:
    text = "Looking for a koh samui villa in August, budget $2000, 4 people"
    score, features = score_signals(text, fetched_at=FRESH, now=NOW)
    assert score == 20 + 25 + 15 + 10 + 5 + 5 == 80
    assert features["kind"] == "guest"
    assert 0 <= score <= 100


def test_scorer_records_kind_in_features() -> None:
    _, features = score_signals(
        "monthly rental villa koh samui for a nomad", fetched_at=OLD, now=NOW
    )
    assert features["kind"] == "longstay"


# ------------------------------------------------------------------ kinds


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Looking for a villa in Koh Samui", "guest"),
        ("หาที่พักที่สมุย 2 คืน", "guest"),
        ("Monthly rental in samui, digital nomad", "longstay"),
        ("Long term stay koh samui", "longstay"),
        ("Organizing a yoga retreat on Koh Samui", "b2b"),
        ("Photographer scouting a photoshoot villa samui", "b2b"),
        ("Need a landscaping company in Samui", "supplier"),
        ("หาเฟอร์นิเจอร์และผู้รับเหมาที่สมุย", "supplier"),
    ],
)
def test_classify_kind(text: str, kind: str) -> None:
    assert classify_kind(text) == kind


def test_detect_language() -> None:
    assert detect_language("สวัสดีครับ") == "th"
    assert detect_language("hello world") == "en"
    assert detect_language("!!! 123") == ""


# ------------------------------------------------------- contact + dedup hash


def test_parse_contact_reddit_handle_from_content() -> None:
    contact = parse_contact(
        "u/somchai_75\nLooking for a villa\n\nbody", "https://www.reddit.com/r/x/1", "reddit"
    )
    assert contact.platform == "reddit"
    assert contact.handle == "u/somchai_75"


def test_parse_contact_rss_falls_back_to_host() -> None:
    contact = parse_contact("A blog post\n\nbody", "https://blog.example.com/post/1", "rss")
    assert contact.platform == "rss"
    assert contact.handle == "blog.example.com"


def test_dedup_hash_normalizes_case_and_whitespace() -> None:
    a = lead_dedup_hash("reddit", "u/jane", "Looking  for a VILLA\n in samui")
    b = lead_dedup_hash("reddit", "u/jane", "looking for a villa in samui")
    assert a == b


def test_dedup_hash_differs_by_handle_and_text() -> None:
    base = lead_dedup_hash("reddit", "u/jane", "text")
    assert lead_dedup_hash("reddit", "u/joe", "text") != base
    assert lead_dedup_hash("reddit", "u/jane", "other text") != base
    assert lead_dedup_hash("rss", "u/jane", "text") != base


def test_excerpt_collapses_whitespace_and_caps_at_300() -> None:
    text = "a  b\n\nc " * 200
    result = excerpt(text)
    assert len(result) <= 300
    assert "\n" not in result and "  " not in result
