"""Rule-based fallback classifier (spec §M3.4) + deterministic summary."""

from __future__ import annotations

from src.domain.change_heuristics import classify_change, fallback_summary
from src.domain.diffing import TextDiff, diff_texts


def _diff(added: tuple[str, ...], ratio: float = 0.1) -> TextDiff:
    return TextDiff(added=added, removed=(), excerpt="", change_ratio=ratio)


def test_thai_price_keyword_is_pricing_high() -> None:
    assert classify_change(_diff(("ห้องเริ่มต้น 4,900 บาท",))) == ("pricing", "high")


def test_baht_symbol_is_pricing_high() -> None:
    assert classify_change(_diff(("weekend rate ฿6,500",))) == ("pricing", "high")


def test_percent_sign_is_pricing_high() -> None:
    assert classify_change(_diff(("save 15% this month",))) == ("pricing", "high")


def test_promotion_keyword_wins_over_pricing() -> None:
    # A promo word plus a price word classifies as promotion, still high.
    assert classify_change(_diff(("โปรโมชั่นพิเศษ ราคาเริ่ม 3,900",))) == ("promotion", "high")


def test_english_discount_and_sale_are_promotion_high() -> None:
    assert classify_change(_diff(("Hot sale — big discount",))) == ("promotion", "high")


def test_room_keywords_are_listing_medium() -> None:
    assert classify_change(_diff(("เปิดจอง ห้องพักใหม่",))) == ("listing", "medium")


def test_villa_and_book_are_listing_medium() -> None:
    assert classify_change(_diff(("New villa now open to book",))) == ("listing", "medium")


def test_other_text_is_content_medium() -> None:
    assert classify_change(_diff(("เปลี่ยนรูปหน้าปกใหม่",))) == ("content", "medium")


def test_major_rewrite_upgrades_severity_to_high() -> None:
    assert classify_change(_diff(("hello world",), ratio=0.8)) == ("content", "high")


def test_major_rewrite_upgrades_listing_to_high() -> None:
    assert classify_change(_diff(("new villa",), ratio=0.9)) == ("listing", "high")


def test_matching_is_case_insensitive() -> None:
    assert classify_change(_diff(("SUMMER SALE",))) == ("promotion", "high")


def test_fallback_summary_is_first_160_chars_of_added_text() -> None:
    long_line = "ราคาใหม่ " + "x" * 300
    summary = fallback_summary(_diff((long_line,)))
    assert len(summary) == 160
    assert summary.startswith("ราคาใหม่ x")
    assert summary.endswith("…")


def test_fallback_summary_joins_short_added_lines() -> None:
    summary = fallback_summary(_diff(("ราคาใหม่ 4,900", "จองได้แล้ววันนี้")))
    assert summary == "ราคาใหม่ 4,900 จองได้แล้ววันนี้"


def test_fallback_summary_handles_no_added_lines() -> None:
    summary = fallback_summary(_diff(()))
    assert summary  # non-empty Thai placeholder
    assert len(summary) <= 160


def test_classifier_works_on_real_diff_output() -> None:
    diff = diff_texts("Pool villa\nOld rate 5,000 THB", "Pool villa\nราคา 4,500 บาท")
    assert classify_change(diff) == ("pricing", "high")
    assert "ราคา 4,500 บาท" in fallback_summary(diff)
