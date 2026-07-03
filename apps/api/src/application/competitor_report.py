"""Weekly competitor report: pure Thai template composer (M3).

Deterministic and LLM-free — this is the fallback body when the ChangeAnalyst
is unavailable or over budget, and the draft the LLM upgrades to an executive
version. Plain text, LINE-friendly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from src.application.ports import WeeklyReportEvent
from src.application.snapshot import format_thai_date

REPORT_TITLE = "รายงานคู่แข่งประจำสัปดาห์"
NO_ACTIVITY_LINE = "ยังไม่พบความเคลื่อนไหว"

# Ordering + plain-text markers, most severe first.
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_MARKERS: dict[str, str] = {
    "critical": "[วิกฤต]",
    "high": "[สำคัญ]",
    "medium": "[ปานกลาง]",
    "low": "[ทั่วไป]",
}

MAX_EVENTS_PER_COMPETITOR = 8
MAX_SUMMARY_CHARS = 160


def _severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, len(SEVERITY_ORDER))


def _marker(severity: str) -> str:
    return SEVERITY_MARKERS.get(severity, f"[{severity}]")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > MAX_SUMMARY_CHARS:
        return text[: MAX_SUMMARY_CHARS - 1] + "…"
    return text


def compose_weekly_report(
    period_start: date, period_end: date, events: Sequence[WeeklyReportEvent]
) -> str:
    """Compose the plain-text Thai weekly report from change events."""
    lines: list[str] = [
        f"{REPORT_TITLE} {format_thai_date(period_start)} - {format_thai_date(period_end)}"
    ]

    if not events:
        lines.append(NO_ACTIVITY_LINE)
        return "\n".join(lines)

    # Group by competitor, preserving first-seen competitor order; within a
    # competitor order by severity (most severe first) then recency.
    grouped: dict[str, list[WeeklyReportEvent]] = {}
    for event in events:
        grouped.setdefault(event.competitor_name, []).append(event)

    for competitor_name, competitor_events in grouped.items():
        competitor_events.sort(
            key=lambda e: (_severity_rank(e.severity), -e.detected_at.timestamp())
        )
        lines.append(f"[{competitor_name}]")
        for event in competitor_events[:MAX_EVENTS_PER_COMPETITOR]:
            lines.append(f"- {_marker(event.severity)} {event.category}: {_clip(event.summary)}")
        hidden = len(competitor_events) - MAX_EVENTS_PER_COMPETITOR
        if hidden > 0:
            lines.append(f"- และอีก {hidden} รายการ")

    return "\n".join(lines)
