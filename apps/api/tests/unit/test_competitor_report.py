"""Weekly competitor report: deterministic Thai composition + the
generate/upgrade/store/push use case (all fakes)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.application.competitor_intel import CompetitorIntelUseCases
from src.application.competitor_report import (
    NO_ACTIVITY_LINE,
    REPORT_TITLE,
    compose_weekly_report,
)
from src.application.ports import WeeklyReportEvent
from tests.fakes import (
    UPGRADE_ACTIONS_HEADER,
    UPGRADE_ANALYSIS_HEADER,
    FakeChangeAnalyst,
    FakeCompetitorIntelRepository,
    FakeFetcher,
    InMemoryObjectStorage,
    NullAuditWriter,
)

ACTOR = "test"
START, END = date(2026, 6, 22), date(2026, 6, 28)


def _event(name: str, category: str, severity: str, summary: str) -> WeeklyReportEvent:
    return WeeklyReportEvent(
        competitor_name=name,
        category=category,
        severity=severity,
        summary=summary,
        detected_at=datetime(2026, 6, 25, tzinfo=UTC),
    )


# -------------------------------------------------------------- composition


def test_empty_week_reports_no_activity() -> None:
    report = compose_weekly_report(START, END, [])
    assert report.startswith(REPORT_TITLE)
    assert NO_ACTIVITY_LINE in report


def test_events_are_grouped_by_competitor_with_thai_markers() -> None:
    report = compose_weekly_report(
        START,
        END,
        [
            _event("Villa A", "pricing", "high", "ลดราคา 20%"),
            _event("Villa B", "content", "low", "เปลี่ยนรูป"),
            _event("Villa A", "promotion", "critical", "แจกฟรี 1 คืน"),
        ],
    )
    lines = report.splitlines()
    assert "[Villa A]" in lines and "[Villa B]" in lines
    # Within Villa A the critical event outranks the high one.
    a_index = lines.index("[Villa A]")
    assert "[วิกฤต]" in lines[a_index + 1] and "แจกฟรี 1 คืน" in lines[a_index + 1]
    assert "[สำคัญ]" in lines[a_index + 2]


def test_long_summaries_are_clipped() -> None:
    report = compose_weekly_report(START, END, [_event("V", "content", "low", "ก" * 500)])
    event_line = next(line for line in report.splitlines() if line.startswith("- "))
    assert len(event_line) < 200 and event_line.endswith("…")


# ----------------------------------------------------------------- use case


def _build(analyst: FakeChangeAnalyst, line_push=None):
    repo = FakeCompetitorIntelRepository()
    use_cases = CompetitorIntelUseCases(
        repo,
        NullAuditWriter(),
        storage=InMemoryObjectStorage(),
        fetcher=FakeFetcher(),
        analyst=analyst,
        line_push=line_push,
    )
    return use_cases, repo


async def _seed_event(repo: FakeCompetitorIntelRepository, summary: str = "ลดราคา") -> None:
    competitor = repo.add_competitor("Villa A")
    await repo.create_change_event(
        competitor_id=competitor.id,
        snapshot_id=None,
        category="pricing",
        summary=summary,
        severity="high",
    )


async def test_generate_stores_upgraded_thai_report_with_iso_week_period() -> None:
    analyst = FakeChangeAnalyst()
    use_cases, repo = _build(analyst)
    await _seed_event(repo)

    result = await use_cases.generate_weekly_report(ACTOR)

    [report] = repo.reports
    assert report.kind == "weekly" and report.lang == "th"
    assert report.period is not None
    year, week = report.period.split("-W")
    assert len(year) == 4 and len(week) == 2  # f"{iso_year}-W{iso_week:02d}"
    assert REPORT_TITLE in report.body
    assert UPGRADE_ANALYSIS_HEADER in report.body  # LLM upgrade applied
    assert UPGRADE_ACTIONS_HEADER in report.body
    assert "ลดราคา" in report.body
    assert result.line_sent is False and report.sent_at is None
    # The analyst was handed the deterministic draft.
    [draft] = analyst.upgrade_calls
    assert draft.startswith(REPORT_TITLE)


async def test_events_older_than_the_window_are_excluded() -> None:
    use_cases, repo = _build(FakeChangeAnalyst(upgrade=False))
    await _seed_event(repo, summary="เก่ามาก")
    repo.change_events[0].detected_at = datetime.now(UTC) - timedelta(days=30)

    await use_cases.generate_weekly_report(ACTOR)

    [report] = repo.reports
    assert "เก่ามาก" not in report.body
    assert NO_ACTIVITY_LINE in report.body


async def test_line_push_success_sets_sent_at() -> None:
    pushed: list[str] = []

    async def push(text: str) -> bool:
        pushed.append(text)
        return True

    use_cases, repo = _build(FakeChangeAnalyst(upgrade=False), line_push=push)
    await _seed_event(repo)

    result = await use_cases.generate_weekly_report(ACTOR)

    assert result.line_sent is True
    assert repo.reports[0].sent_at is not None
    assert REPORT_TITLE in pushed[0]


async def test_line_push_failure_is_non_fatal() -> None:
    async def push(text: str) -> bool:
        raise ConnectionError("LINE down")

    use_cases, repo = _build(FakeChangeAnalyst(upgrade=False), line_push=push)
    await _seed_event(repo)

    result = await use_cases.generate_weekly_report(ACTOR)

    assert result.line_sent is False
    [report] = repo.reports  # stored anyway
    assert report.sent_at is None


async def test_upgrade_fallback_keeps_the_draft() -> None:
    use_cases, repo = _build(FakeChangeAnalyst(upgrade=False))
    await _seed_event(repo)

    await use_cases.generate_weekly_report(ACTOR)

    [report] = repo.reports
    assert report.body.startswith(REPORT_TITLE)
    assert UPGRADE_ANALYSIS_HEADER not in report.body  # draft unchanged
