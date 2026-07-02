"""Daily Thai snapshot composition: fixed inputs, exact output."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.application.snapshot import (
    SiteSnapshot,
    compose_daily_snapshot,
    format_baht,
    format_thai_date,
    week_start_bangkok,
)
from src.domain.bank_alerts import BANGKOK_TZ


def site(**overrides: object) -> SiteSnapshot:
    defaults: dict = dict(
        name="Lipa Noi",
        pending_draw_count=0,
        pending_draw_total_thb=Decimal("0"),
        paid_this_week_thb=Decimal("0"),
        awaiting_confirmation_count=0,
        overdue_milestones=(),
    )
    defaults.update(overrides)
    return SiteSnapshot(**defaults)


class TestFormatting:
    def test_whole_baht_has_no_satang(self) -> None:
        assert format_baht(Decimal("50000")) == "฿50,000"

    def test_satang_shown_when_present(self) -> None:
        assert format_baht(Decimal("1234.50")) == "฿1,234.50"

    def test_thai_date_uses_buddhist_era(self) -> None:
        assert format_thai_date(date(2026, 7, 2)) == "2 ก.ค. 2569"


class TestComposition:
    def test_snapshot_lists_each_site_with_figures(self) -> None:
        body = compose_daily_snapshot(
            date(2026, 7, 2),
            [
                site(
                    name="Lipa Noi",
                    pending_draw_count=2,
                    pending_draw_total_thb=Decimal("150000"),
                    paid_this_week_thb=Decimal("80000"),
                ),
                site(name="Chaweng", paid_this_week_thb=Decimal("25000.50")),
            ],
        )
        assert body.startswith("สรุปประจำวัน 2 ก.ค. 2569")
        assert "[Lipa Noi]" in body
        assert "ยอดเบิกรอจ่าย: 2 รายการ รวม ฿150,000" in body
        assert "จ่ายแล้วสัปดาห์นี้: ฿80,000" in body
        assert "[Chaweng]" in body
        assert "฿25,000.50" in body

    def test_awaiting_confirmations_are_the_top_action(self) -> None:
        body = compose_daily_snapshot(
            date(2026, 7, 2),
            [
                site(awaiting_confirmation_count=2),
                site(name="Chaweng", awaiting_confirmation_count=1),
            ],
        )
        assert body.endswith("สิ่งสำคัญที่สุด: มีรายการโอน 3 รายการรอยืนยันการจับคู่")

    def test_overdue_milestones_rank_second(self) -> None:
        body = compose_daily_snapshot(
            date(2026, 7, 2),
            [site(overdue_milestones=("งานไฟฟ้าชั้น 2",), pending_draw_count=1)],
        )
        assert "milestone เลยกำหนด: งานไฟฟ้าชั้น 2" in body
        assert "สิ่งสำคัญที่สุด: มี milestone เลยกำหนด 1 รายการ" in body

    def test_quiet_day_message(self) -> None:
        body = compose_daily_snapshot(date(2026, 7, 2), [site()])
        assert body.endswith("สิ่งสำคัญที่สุด: วันนี้ไม่มีเรื่องเร่งด่วน")

    def test_stays_line_friendly_length(self) -> None:
        body = compose_daily_snapshot(
            date(2026, 7, 2),
            [
                site(
                    pending_draw_count=3,
                    pending_draw_total_thb=Decimal("500000"),
                    paid_this_week_thb=Decimal("100000"),
                    awaiting_confirmation_count=1,
                    overdue_milestones=("a", "b"),
                ),
                site(name="Chaweng", pending_draw_count=1),
            ],
        )
        assert len(body.splitlines()) <= 15


class TestWeekStart:
    def test_monday_bangkok_wall_clock(self) -> None:
        # Thursday 2026-07-02 10:00 Bangkok -> Monday 2026-06-29 00:00 Bangkok
        now = datetime(2026, 7, 2, 10, 0, tzinfo=BANGKOK_TZ)
        start = week_start_bangkok(now)
        assert start == datetime(2026, 6, 29, 0, 0, tzinfo=BANGKOK_TZ)

    def test_monday_maps_to_itself(self) -> None:
        now = datetime(2026, 6, 29, 0, 30, tzinfo=BANGKOK_TZ)
        assert week_start_bangkok(now) == datetime(2026, 6, 29, tzinfo=BANGKOK_TZ)
