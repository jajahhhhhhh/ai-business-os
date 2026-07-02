"""Daily Thai snapshot: composition (pure) + generate/store/push use case.

The message is plain text, LINE-friendly, and kept to roughly 15 lines:
per-site pending draws, this week's payments, matched-but-unconfirmed bank
transactions, overdue milestones, and the single most important action.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.application.repositories import AuditWriter, ReportRow
from src.domain.bank_alerts import BANGKOK_TZ

_THAI_MONTH_ABBREV = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)
_BE_OFFSET = 543


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Per-site figures the composer needs; gathered by the repository."""

    name: str
    pending_draw_count: int
    pending_draw_total_thb: Decimal
    paid_this_week_thb: Decimal
    awaiting_confirmation_count: int
    overdue_milestones: tuple[str, ...]


def format_baht(amount: Decimal) -> str:
    """฿ with thousands commas; satang shown only when non-zero."""
    if amount == amount.to_integral_value():
        return f"฿{amount:,.0f}"
    return f"฿{amount:,.2f}"


def format_thai_date(day: date) -> str:
    """Thai short date with Buddhist-era year, e.g. '2 ก.ค. 2569'."""
    return f"{day.day} {_THAI_MONTH_ABBREV[day.month - 1]} {day.year + _BE_OFFSET}"


def _top_action(sites: Sequence[SiteSnapshot]) -> str:
    awaiting = sum(site.awaiting_confirmation_count for site in sites)
    if awaiting:
        return f"มีรายการโอน {awaiting} รายการรอยืนยันการจับคู่"
    overdue = sum(len(site.overdue_milestones) for site in sites)
    if overdue:
        return f"มี milestone เลยกำหนด {overdue} รายการ ควรอัปเดตแผนงาน"
    pending_count = sum(site.pending_draw_count for site in sites)
    if pending_count:
        pending_total = sum(
            (site.pending_draw_total_thb for site in sites), Decimal("0")
        )
        return f"มียอดเบิกรอจ่าย {pending_count} รายการ รวม {format_baht(pending_total)}"
    return "วันนี้ไม่มีเรื่องเร่งด่วน"


def compose_daily_snapshot(today: date, sites: Sequence[SiteSnapshot]) -> str:
    """Compose the plain-text Thai daily snapshot (LINE-friendly)."""
    lines: list[str] = [f"สรุปประจำวัน {format_thai_date(today)}"]
    for site in sites:
        lines.append(f"[{site.name}]")
        lines.append(
            f"- ยอดเบิกรอจ่าย: {site.pending_draw_count} รายการ"
            f" รวม {format_baht(site.pending_draw_total_thb)}"
        )
        lines.append(f"- จ่ายแล้วสัปดาห์นี้: {format_baht(site.paid_this_week_thb)}")
        lines.append(f"- งวดที่รอการยืนยัน: {site.awaiting_confirmation_count} รายการ")
        if site.overdue_milestones:
            lines.append(f"- milestone เลยกำหนด: {', '.join(site.overdue_milestones)}")
    lines.append(f"สิ่งสำคัญที่สุด: {_top_action(sites)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ use case

LinePush = Callable[[str], Awaitable[bool]]


class SnapshotRepository(Protocol):
    async def site_snapshots(
        self, week_start: datetime, today: date
    ) -> Sequence[SiteSnapshot]: ...
    async def create_report(
        self, *, kind: str, period: str, lang: str, body: str, sent_at: datetime | None
    ) -> ReportRow: ...


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    report: ReportRow
    line_sent: bool


def week_start_bangkok(now: datetime) -> datetime:
    """Monday 00:00 of the current week, Bangkok wall clock."""
    local = now.astimezone(BANGKOK_TZ)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=BANGKOK_TZ)


class DailySnapshotUseCases:
    def __init__(
        self,
        repo: SnapshotRepository,
        audit: AuditWriter,
        line_push: LinePush | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._line_push = line_push

    async def generate(self, actor: str, now: datetime | None = None) -> SnapshotResult:
        now = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
        today = now.date()
        sites = await self._repo.site_snapshots(week_start_bangkok(now), today)
        body = compose_daily_snapshot(today, sites)

        # LINE delivery must never fail report generation; the client already
        # swallows and logs transport errors, this guard is belt-and-braces.
        line_sent = False
        if self._line_push is not None:
            try:
                line_sent = await self._line_push(body)
            except Exception:  # noqa: BLE001 - push failure is non-fatal by design
                line_sent = False

        report = await self._repo.create_report(
            kind="daily",
            period=today.isoformat(),
            lang="th",
            body=body,
            sent_at=now if line_sent else None,
        )
        await self._audit.write(
            actor,
            "report.generated",
            "reports",
            report.id,
            {"kind": "daily", "period": today.isoformat(), "line_sent": line_sent},
        )
        return SnapshotResult(report=report, line_sent=line_sent)
