"""Competitor intelligence use cases (M3): sources, sweeps, weekly report.

Compliance (§8.4) is enforced in code, not by convention:
- register_source validates every URL through the REAL ComplianceGate.check_url
  (module-level, never swapped by test fakes) — facebook/OTA domains are
  structurally impossible to register (hard blocklist in collectors).
- Sweeps fetch through the injected gate (ComplianceGate in production, fake
  in tests), so robots.txt + rate limits guard every outbound request.

NFR-1: a failed source (refused / HTTP error / parse error) records its
last_status and the sweep continues — one bad source never stops the rest.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
from collectors.compliance import ComplianceGate, ComplianceViolation, SourcePolicy, TosPolicy

from src.application.competitor_report import (
    SEVERITY_ORDER,
    compose_weekly_report,
)
from src.application.errors import ComplianceRefusedError, NotFoundError
from src.application.ports import (
    ChangeAnalyst,
    ObjectStorage,
    WeeklyReportContext,
    WeeklyReportEvent,
)
from src.application.repositories import (
    AuditWriter,
    ChangeEventDisplayRow,
    CompetitorIntelRepository,
    ReportRow,
    SourceDisplayRow,
    SourceRow,
)
from src.domain.bank_alerts import BANGKOK_TZ
from src.domain.change_heuristics import classify_change
from src.domain.diffing import diff_texts
from src.domain.html_text import html_to_text

logger = structlog.get_logger("application.competitor_intel")

SOURCE_TYPES = ("website", "rss", "sitemap")
DEFAULT_RATE_LIMIT_PER_HR = 6

BASELINE_SUMMARY_TH = "เริ่มติดตามแหล่งข้อมูลนี้"
FALLBACK_SUMMARY_PREFIX = "พบการเปลี่ยนแปลง: "
FALLBACK_SUMMARY_MAX_CHARS = 300
FALLBACK_SUMMARY_MAX_LINES = 3

WEEKLY_REPORT_DAYS = 7
LINE_PUSH_MAX_LINES = 40

# Registration validation always goes through a real gate: the hard blocklist
# and ToS checks are structural guarantees, never replaced by test fakes.
# check_url is pure (no I/O) — the gate's HTTP client is never used here.
_registration_gate = ComplianceGate()


class ComplianceFetcher(Protocol):
    """The fetch surface of collectors.compliance.ComplianceGate."""

    async def fetch(self, policy: SourcePolicy, url: str) -> str: ...


LinePush = Callable[[str], Awaitable[bool]]


@dataclass(slots=True)
class SweepStats:
    sources: int = 0
    fetched: int = 0
    unchanged: int = 0
    changed: int = 0
    refused: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "fetched": self.fetched,
            "unchanged": self.unchanged,
            "changed": self.changed,
            "refused": self.refused,
            "errors": self.errors,
        }


@dataclass(frozen=True, slots=True)
class WeeklyReportResult:
    report: ReportRow
    line_sent: bool
    llm_used: bool


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_policy(source: SourceRow) -> SourcePolicy:
    return SourcePolicy(
        name=str(source.id),  # rate-limit bucket key
        tos_policy=TosPolicy(source.tos_policy),
        rate_limit_per_hr=source.rate_limit_per_hr,
        enabled=source.enabled,
    )


def fallback_summary(added: tuple[str, ...], excerpt: str) -> str:
    """Thai summary used when the LLM is unavailable: first added lines."""
    lines = [line.strip() for line in added if line.strip()]
    if not lines:
        lines = [line.strip() for line in excerpt.splitlines() if line.strip()][1:]
    body = " | ".join(lines[:FALLBACK_SUMMARY_MAX_LINES])
    summary = FALLBACK_SUMMARY_PREFIX + (body or "เนื้อหาบนหน้าเว็บเปลี่ยนไปจากเดิม")
    if len(summary) > FALLBACK_SUMMARY_MAX_CHARS:
        summary = summary[: FALLBACK_SUMMARY_MAX_CHARS - 1] + "…"
    return summary


class CompetitorIntelUseCases:
    def __init__(
        self,
        repo: CompetitorIntelRepository,
        audit: AuditWriter,
        *,
        storage: ObjectStorage,
        gate: ComplianceFetcher,
        analyst: ChangeAnalyst,
        line_push: LinePush | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._storage = storage
        self._gate = gate
        self._analyst = analyst
        self._line_push = line_push

    # ------------------------------------------------------------- sources

    async def register_source(
        self,
        *,
        name: str,
        type: str,  # noqa: A002 - mirrors the column name
        url: str,
        competitor_id: uuid.UUID | None,
        rate_limit_per_hr: int = DEFAULT_RATE_LIMIT_PER_HR,
        actor: str,
    ) -> SourceRow:
        if type not in SOURCE_TYPES:
            raise ComplianceRefusedError("invalid_type", f"source type {type!r} not allowed")
        if competitor_id is not None and await self._repo.get_competitor(competitor_id) is None:
            raise NotFoundError("competitor", competitor_id)

        policy = SourcePolicy(
            name=name, tos_policy=TosPolicy.ALLOWED, rate_limit_per_hr=rate_limit_per_hr
        )
        try:
            _registration_gate.check_url(policy, url)
        except ComplianceViolation as exc:
            raise ComplianceRefusedError(exc.reason, str(exc)) from exc

        source = await self._repo.create_source(
            name=name,
            type=type,
            url=url,
            competitor_id=competitor_id,
            rate_limit_per_hr=rate_limit_per_hr,
            tos_policy=TosPolicy.ALLOWED.value,
            robots_ok=True,
            enabled=True,
        )
        await self._audit.write(
            actor,
            "source.registered",
            "sources",
            source.id,
            {"name": name, "type": type, "url": url, "competitor_id": str(competitor_id or "")},
        )
        return source

    # -------------------------------------------------------------- sweeps

    async def sweep_competitor(self, competitor_id: uuid.UUID, actor: str) -> dict[str, int]:
        competitor = await self._repo.get_competitor(competitor_id)
        if competitor is None:
            raise NotFoundError("competitor", competitor_id)
        return await self._sweep(competitor_id, actor)

    async def sweep_all(self, actor: str) -> dict[str, int]:
        return await self._sweep(None, actor)

    async def _sweep(self, competitor_id: uuid.UUID | None, actor: str) -> dict[str, int]:
        sources = await self._repo.sweep_sources(competitor_id)
        stats = SweepStats(sources=len(sources))
        for source in sources:
            try:
                await self._sweep_source(source, stats)
            except Exception as exc:  # noqa: BLE001 - NFR-1: never stop the sweep
                logger.warning(
                    "sweep_source_failed", source_id=str(source.id), error=str(exc)
                )
                stats.errors += 1
                await self._repo.set_source_result(source.id, "error", datetime.now(UTC))
        await self._audit.write(
            actor,
            "competitors.swept",
            "competitors",
            competitor_id,
            stats.as_dict(),
        )
        return stats.as_dict()

    async def _sweep_source(self, source: SourceDisplayRow, stats: SweepStats) -> None:
        assert source.competitor_id is not None  # sweep_sources filters these
        assert source.url is not None
        now = datetime.now(UTC)

        try:
            html = await self._gate.fetch(_source_policy(source), source.url)
        except ComplianceViolation as exc:
            logger.info("sweep_fetch_refused", source_id=str(source.id), reason=exc.reason)
            stats.refused += 1
            await self._repo.set_source_result(source.id, "refused", now)
            return
        except Exception as exc:  # noqa: BLE001 - HTTP/network errors are per-source
            logger.warning("sweep_fetch_error", source_id=str(source.id), error=str(exc))
            stats.errors += 1
            await self._repo.set_source_result(source.id, "error", now)
            return

        stats.fetched += 1
        text = html_to_text(html)
        content_hash = _content_hash(text)
        previous = await self._repo.latest_snapshot(source.competitor_id, source.id)

        if previous is not None and previous.content_hash == content_hash:
            # Short-circuit BEFORE any storage write: nothing changed.
            stats.unchanged += 1
            await self._repo.set_source_result(source.id, "unchanged", now)
            return

        storage_key = (
            f"snapshots/{source.competitor_id}/{source.id}/"
            f"{now.strftime('%Y%m%dT%H%M%S')}-{content_hash[:8]}.txt"
        )
        await self._storage.put(storage_key, text.encode("utf-8"), "text/plain; charset=utf-8")
        snapshot = await self._repo.create_snapshot(
            competitor_id=source.competitor_id,
            source_id=source.id,
            content_hash=content_hash,
            storage_key=storage_key,
        )

        if previous is None:
            # First snapshot: baseline marker, deliberately NO LLM call.
            await self._repo.create_change_event(
                competitor_id=source.competitor_id,
                snapshot_id=snapshot.id,
                category="baseline",
                summary=BASELINE_SUMMARY_TH,
                severity="low",
            )
        else:
            previous_text = (await self._storage.get(previous.storage_key)).decode("utf-8")
            diff = diff_texts(previous_text, text)
            analysis = None
            if self._analyst.is_available:
                analysis = await self._analyst.analyze_change(
                    source.competitor_name or source.name, source.url, diff.excerpt
                )
            if analysis is not None:
                category, severity, summary = (
                    analysis.category,
                    analysis.severity,
                    analysis.summary_th,
                )
            else:
                category, severity = classify_change(diff)
                summary = fallback_summary(diff.added, diff.excerpt)
            await self._repo.create_change_event(
                competitor_id=source.competitor_id,
                snapshot_id=snapshot.id,
                category=category,
                summary=summary,
                severity=severity,
            )

        stats.changed += 1
        await self._repo.set_source_result(source.id, "changed", now)

    # ------------------------------------------------------- weekly report

    async def generate_weekly_report(
        self, actor: str, now: datetime | None = None
    ) -> WeeklyReportResult:
        now = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
        since = now - timedelta(days=WEEKLY_REPORT_DAYS)
        period_start, period_end = since.date(), now.date()

        rows = await self._repo.change_events_since(since)
        events = tuple(
            WeeklyReportEvent(
                competitor_name=row.competitor_name,
                category=row.category,
                severity=row.severity,
                summary=row.summary,
                detected_at=row.detected_at,
            )
            for row in _severity_sorted(rows)
        )
        template = compose_weekly_report(period_start, period_end, events)

        body, llm_used = template, False
        if self._analyst.is_available:
            report_text = await self._analyst.compose_weekly_report(
                WeeklyReportContext(
                    period_start=period_start,
                    period_end=period_end,
                    template_report=template,
                    events=events,
                )
            )
            if report_text is not None:
                body, llm_used = report_text.text, True

        line_sent = False
        if self._line_push is not None:
            try:
                line_sent = await self._line_push(
                    "\n".join(body.splitlines()[:LINE_PUSH_MAX_LINES])
                )
            except Exception:  # noqa: BLE001 - push failure is non-fatal by design
                line_sent = False

        report = await self._repo.create_report(
            kind="weekly",
            period=f"{period_start.isoformat()}/{period_end.isoformat()}",
            lang="th",
            body=body,
            sent_at=now if line_sent else None,
        )
        await self._audit.write(
            actor,
            "report.generated",
            "reports",
            report.id,
            {
                "kind": "weekly",
                "events": len(events),
                "llm_used": llm_used,
                "line_sent": line_sent,
            },
        )
        return WeeklyReportResult(report=report, line_sent=line_sent, llm_used=llm_used)


def _severity_sorted(
    rows: Sequence[ChangeEventDisplayRow],
) -> list[ChangeEventDisplayRow]:
    """Competitor-name groups stay together; severest first within a group."""
    return sorted(
        rows,
        key=lambda row: (
            row.competitor_name,
            SEVERITY_ORDER.get(row.severity, len(SEVERITY_ORDER)),
            -row.detected_at.timestamp(),
        ),
    )
