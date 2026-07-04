"""Planner fallback rules (pure): priority order and Thai composition."""

from __future__ import annotations

from decimal import Decimal

from src.application.agents.planning import (
    NO_FOCUS_LINE_TH,
    PLAN_HEADER_TH,
    CompetitorSignal,
    PlannerInputs,
    compose_fallback_plan,
    focus_items,
    format_inputs_th,
)

FULL_INPUTS = PlannerInputs(
    eval_averages={"analytics": Decimal("82"), "memory": Decimal("95")},
    overdue_milestones=("Lipa Noi — งานไฟฟ้า", "Chaweng — งานสี"),
    unconfirmed_count=3,
    competitor_signals=(CompetitorSignal("Villa B", "ลดราคา 20%", "critical"),),
)


def test_focus_order_milestones_then_payments_then_competitors() -> None:
    items = focus_items(FULL_INPUTS)
    assert len(items) == 3
    assert "milestone" in items[0] and "Lipa Noi — งานไฟฟ้า" in items[0]
    assert "ยืนยันรายการโอน" in items[1] and "3 รายการ" in items[1]
    assert "คู่แข่ง" in items[2] and "Villa B" in items[2]


def test_missing_rule_inputs_drop_out_but_order_holds() -> None:
    inputs = PlannerInputs(
        unconfirmed_count=2,
        competitor_signals=(CompetitorSignal("Villa C", "โปรใหม่", "high"),),
    )
    items = focus_items(inputs)
    assert len(items) == 2
    assert "ยืนยันรายการโอน" in items[0]  # payments move up when no milestones
    assert "คู่แข่ง" in items[1]


def test_fallback_plan_header_and_numbering() -> None:
    plan = compose_fallback_plan("2026-W27", FULL_INPUTS)
    lines = plan.splitlines()
    assert lines[0] == f"{PLAN_HEADER_TH} 2026-W27"
    assert lines[1].startswith("1) ") and lines[2].startswith("2) ")
    assert lines[3].startswith("3) ")
    # Eval health is appended as context, pointing at the weakest agent.
    assert "analytics" in lines[4] and "82" in lines[4]


def test_quiet_week_message() -> None:
    plan = compose_fallback_plan("2026-W27", PlannerInputs())
    assert NO_FOCUS_LINE_TH in plan


def test_long_milestone_lists_are_clipped() -> None:
    inputs = PlannerInputs(overdue_milestones=tuple(f"ไซต์ — งาน {i}" for i in range(5)))
    [item] = focus_items(inputs)
    assert "และอีก 2 รายการ" in item


def test_format_inputs_covers_every_signal_for_the_prompt() -> None:
    block = format_inputs_th(FULL_INPUTS)
    assert "milestone เลยกำหนด 2 รายการ" in block
    assert "รอยืนยัน: 3 รายการ" in block
    assert "Villa B [critical]" in block
    assert "analytics=82" in block
