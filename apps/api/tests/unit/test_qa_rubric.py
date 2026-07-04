"""QA deterministic rubric (pure): section checks, Thai detection, bounds."""

from __future__ import annotations

from src.application.agents.rubric import (
    blend_scores,
    parse_llm_score,
    score_report,
    score_run_health,
)

GOOD_DAILY = (
    "สรุปประจำวัน 4 ก.ค. 2569\n[Lipa Noi]\n- ยอดเบิกรอจ่าย: 1 รายการ รวม ฿10,000\n"
    "สิ่งสำคัญที่สุด: ไม่มีเรื่องเร่งด่วน"
)
GOOD_WEEKLY = "รายงานคู่แข่งประจำสัปดาห์ 22 มิ.ย. 2569 - 4 ก.ค. 2569\nยังไม่พบความเคลื่อนไหว"
GOOD_PLAN = "แผนสัปดาห์ 2026-W27\n1) เร่งตาม milestone ที่เลยกำหนด 2 รายการ ให้ครบก่อนศุกร์นี้"


def test_perfect_reports_score_100() -> None:
    for kind, body in (("daily", GOOD_DAILY), ("weekly", GOOD_WEEKLY), ("planning", GOOD_PLAN)):
        score, notes = score_report(kind, body)
        assert score == 100, (kind, notes)
        assert notes == "ผ่านเกณฑ์ทุกข้อ"


def test_empty_body_scores_zero() -> None:
    assert score_report("daily", None)[0] == 0
    assert score_report("daily", "   ")[0] == 0


def test_missing_thai_content_is_penalized() -> None:
    body = "Daily summary 2026-07-04 | " + "pending draws: 1 | " * 5
    score, notes = score_report("weekly", body)
    assert score < 100
    assert "ไม่พบข้อความภาษาไทย" in notes


def test_missing_sections_are_penalized_proportionally() -> None:
    # Daily requires two sections; drop one -> half the section points.
    body = "สรุปประจำวัน 4 ก.ค. 2569\n" + "รายละเอียดงานก่อสร้างเพิ่มเติมอีกมากมาย"
    score, notes = score_report("daily", body)
    assert score == 80  # 100 - 40/2
    assert "สิ่งสำคัญที่สุด" in notes


def test_length_bounds_are_enforced_per_kind() -> None:
    too_short = "สั้นไป"
    score, notes = score_report("planning", too_short)
    assert score < 100 and "ความยาว" in notes

    too_long = "แผนสัปดาห์ " + "ก" * 5_000
    score, notes = score_report("planning", too_long)
    assert "ความยาว" in notes


def test_unknown_kind_uses_default_bounds_and_no_sections() -> None:
    score, _ = score_report("custom", "รายงานภาษาไทยที่ยาวพอสมควรสำหรับการทดสอบเกณฑ์นี้")
    assert score == 100


def test_run_health_rubric() -> None:
    assert score_run_health("succeeded")[0] == 100
    assert score_run_health("failed")[0] == 0
    assert score_run_health("parked")[0] == 0


def test_blend_is_50_50_clamped() -> None:
    assert blend_scores(100, 50) == 75
    assert blend_scores(0, 100) == 50
    assert blend_scores(100, 100) == 100


def test_parse_llm_score_variants() -> None:
    assert parse_llm_score('{"score": 88, "notes": "ดี"}') == (88, "ดี")
    assert parse_llm_score('ผล:\n{"score": 40, "notes": "ขาดหัวข้อ"}\nจบ') == (40, "ขาดหัวข้อ")
    assert parse_llm_score('{"score": 250, "notes": ""}') == (100, "")  # clamped
    assert parse_llm_score("ไม่มี json") is None
    assert parse_llm_score('{"notes": "no score"}') is None
