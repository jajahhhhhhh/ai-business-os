"""Planner agent pure logic: weekly-plan inputs, Thai fallback composition.

LLM-free and orchestrator-free so the rule-based fallback is unit-testable
anywhere. Rule order (deliverable spec): overdue milestones first, matched-
but-unconfirmed bank transactions second, critical/high competitor moves
third; agent-eval health is appended as context, never as a focus item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

PLAN_HEADER_TH = "แผนสัปดาห์"
NO_FOCUS_LINE_TH = "ไม่มีเรื่องเร่งด่วน — เดินหน้าตามแผนงานเดิมของทั้งสองไซต์"
TOP_FOCUS_COUNT = 3
MAX_LISTED_ITEMS = 3  # milestones/events shown inline per focus item


@dataclass(frozen=True, slots=True)
class CompetitorSignal:
    competitor_name: str
    summary: str
    severity: str


@dataclass(frozen=True, slots=True)
class PlannerInputs:
    """Everything the planner reads (gathered by the PlannerGateway)."""

    eval_averages: dict[str, Decimal] = field(default_factory=dict)  # agent -> avg 0-100, last 7d
    overdue_milestones: tuple[str, ...] = ()  # "site — milestone" labels
    unconfirmed_count: int = 0  # matched-but-unconfirmed bank transactions
    competitor_signals: tuple[CompetitorSignal, ...] = ()  # high/critical, last 7d


def _clip_list(items: tuple[str, ...]) -> str:
    shown = ", ".join(items[:MAX_LISTED_ITEMS])
    hidden = len(items) - MAX_LISTED_ITEMS
    return f"{shown} และอีก {hidden} รายการ" if hidden > 0 else shown


def focus_items(inputs: PlannerInputs) -> list[str]:
    """Rule-based top focus items, in mandated priority order."""
    items: list[str] = []
    if inputs.overdue_milestones:
        items.append(
            f"เร่งตาม milestone ที่เลยกำหนด {len(inputs.overdue_milestones)} รายการ: "
            f"{_clip_list(inputs.overdue_milestones)}"
        )
    if inputs.unconfirmed_count:
        items.append(f"ยืนยันรายการโอนที่จับคู่แล้วแต่ยังไม่ยืนยัน {inputs.unconfirmed_count} รายการ")
    if inputs.competitor_signals:
        names = tuple(
            f"{signal.competitor_name} ({signal.summary})" for signal in inputs.competitor_signals
        )
        items.append(
            f"ตอบสนองความเคลื่อนไหวสำคัญของคู่แข่ง {len(inputs.competitor_signals)} รายการ: "
            f"{_clip_list(names)}"
        )
    return items[:TOP_FOCUS_COUNT]


def compose_fallback_plan(period: str, inputs: PlannerInputs) -> str:
    """Deterministic Thai weekly plan (LINE-friendly plain text)."""
    lines = [f"{PLAN_HEADER_TH} {period}"]
    items = focus_items(inputs)
    if items:
        lines.extend(f"{index}) {item}" for index, item in enumerate(items, start=1))
    else:
        lines.append(NO_FOCUS_LINE_TH)
    if inputs.eval_averages:
        worst_agent = min(inputs.eval_averages, key=lambda a: inputs.eval_averages[a])
        lines.append(
            f"คุณภาพเอเจนต์สัปดาห์ก่อน: {worst_agent} ได้คะแนนเฉลี่ยต่ำสุด "
            f"{inputs.eval_averages[worst_agent]:.0f}/100"
        )
    return "\n".join(lines)


def format_inputs_th(inputs: PlannerInputs) -> str:
    """Render the gathered inputs as Thai bullet lines for the LLM prompt."""
    lines: list[str] = []
    if inputs.overdue_milestones:
        lines.append(
            f"- milestone เลยกำหนด {len(inputs.overdue_milestones)} รายการ: "
            f"{_clip_list(inputs.overdue_milestones)}"
        )
    else:
        lines.append("- ไม่มี milestone เลยกำหนด")
    lines.append(f"- รายการโอนที่จับคู่แล้วรอยืนยัน: {inputs.unconfirmed_count} รายการ")
    if inputs.competitor_signals:
        for signal in inputs.competitor_signals[: MAX_LISTED_ITEMS * 2]:
            lines.append(f"- คู่แข่ง {signal.competitor_name} [{signal.severity}]: {signal.summary}")
    else:
        lines.append("- ไม่มีความเคลื่อนไหวสำคัญของคู่แข่ง")
    if inputs.eval_averages:
        pairs = ", ".join(
            f"{agent}={score:.0f}" for agent, score in sorted(inputs.eval_averages.items())
        )
        lines.append(f"- คะแนนเฉลี่ยคุณภาพเอเจนต์ 7 วันล่าสุด: {pairs}")
    return "\n".join(lines)


# Inline fallback for packages/prompts/planner/weekly_plan.th.j2.
# Required template variables: period, inputs (pre-rendered Thai bullet block).
WEEKLY_PLAN_PROMPT_FALLBACK_TH = (
    "คุณเป็นผู้ช่วยวางแผนของเจ้าของโครงการรีโนเวทวิลล่า 2 ไซต์บนเกาะสมุย\n"
    "ข้อมูลสถานะล่าสุด:\n"
    "{{ inputs }}\n\n"
    f'เขียน "{PLAN_HEADER_TH} {{{{ period }}}}" เป็นภาษาไทย: เลือกเรื่องที่ควรโฟกัส 3 อันดับ\n'
    "พร้อมเหตุผลสั้น ๆ ต่อข้อ (บรรทัดละข้อ ขึ้นต้น 1) 2) 3))\n"
    f'บรรทัดแรกต้องเป็น "{PLAN_HEADER_TH} {{{{ period }}}}" เท่านั้น\n'
    "ตอบเป็นข้อความล้วน (plain text) ไม่ใช้ markdown อ่านง่ายใน LINE"
)
