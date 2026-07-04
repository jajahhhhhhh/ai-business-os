"""Competitor intelligence use cases (M3): registry, sweeps, weekly report.

Compliance (§8.4) is enforced in code, not by convention:
- Registration validates every source URL against the collectors
  HARD_BLOCKLIST (facebook/OTA domains are structurally impossible to
  register). The collectors package is imported LAZILY with a local mirror of
  the blocklist as fallback, so the API tree imports cleanly when the
  optional package is absent (same availability-gating philosophy as
  BgeM3Embedder).
- Sweeps fetch through the injected Fetcher port (ComplianceGate adapter in
  production, fake in tests), so robots.txt + rate limits guard every
  outbound request.

NFR-1: a failed source (blocked / HTTP error / parse error) records its
last_status ('blocked: ...' / 'error: ...') and the sweep continues — one bad
source never stops the rest, and a sweep never raises out of a worker task.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import structlog

from src.application.competitor_report import SEVERITY_ORDER, compose_weekly_report
from src.application.errors import ComplianceRefusedError, NotFoundError
from src.application.ports import (
    ChangeAnalyst,
    Fetcher,
    FetchPolicy,
    ObjectStorage,
    WeeklyReportEvent,
)
from src.application.repositories import (
    AuditWriter,
    ChangeEventDisplayRow,
    CompetitorIntelRepository,
    CompetitorRow,
    ReportRow,
    SourceDisplayRow,
    SourceRow,
)
from src.application.snapshot import week_start_bangkok
from src.domain.bank_alerts import BANGKOK_TZ
from src.domain.change_heuristics import classify_change, fallback_summary
from src.domain.diffing import diff_texts
from src.domain.html_text import html_to_text
from src.domain.rss_text import rss_to_text

logger = structlog.get_logger("application.competitor_intel")

SOURCE_TYPES = ("website", "rss")
DEFAULT_RATE_LIMIT_PER_HR = 6

STATUS_DETAIL_MAX_CHARS = 120

WEEKLY_REPORT_DAYS = 7
LINE_PUSH_MAX_LINES = 40

# Mirror of collectors.compliance.HARD_BLOCKLIST, used only when the optional
# collectors package is not installed (API-only test environments). KEEP IN
# SYNC — the container always has collectors, so production uses the real one.
_HARD_BLOCKLIST_MIRROR: frozenset[str] = frozenset(
    {
        "facebook.com",
        "fb.com",
        "instagram.com",
        "airbnb.com",
        "airbnb.co.th",
        "booking.com",
        "agoda.com",
    }
)

REFUSAL_DETAIL_TH = (
    "ไม่สามารถลงทะเบียนแหล่งข้อมูล {url} ได้ — โดเมนนี้อยู่ในรายการห้ามเก็บข้อมูล "
    "(Facebook / Airbnb / Booking / Agoda) ตามนโยบายแหล่งข้อมูล §8.4 "
    "กรุณาใช้เว็บไซต์ทางการหรือ RSS ของคู่แข่งแทน"
)
INVALID_URL_DETAIL_TH = (
    "URL ไม่ถูกต้อง: {url} — ต้องเป็นลิงก์ http/https ที่ระบุโดเมนชัดเจน (นโยบายแหล่งข้อมูล §8.4)"
)


def _hard_blocklist() -> frozenset[str]:
    try:  # lazy: the collectors package is optional outside the container
        from collectors.compliance import HARD_BLOCKLIST

        return HARD_BLOCKLIST
    except ImportError:
        return _HARD_BLOCKLIST_MIRROR


def check_url_compliance(url: str) -> None:
    """Refuse blocklisted/invalid URLs at registration time (§8.4).

    Pure (no I/O) and structural: raises ComplianceRefusedError -> HTTP 422
    with a Thai-readable detail referencing the §8.4 source policy.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ComplianceRefusedError("invalid_url", INVALID_URL_DETAIL_TH.format(url=url))
    host = parsed.hostname.lower().rstrip(".")
    if any(host == d or host.endswith("." + d) for d in _hard_blocklist()):
        raise ComplianceRefusedError("hard_blocklist", REFUSAL_DETAIL_TH.format(url=url))


LinePush = Callable[[str], Awaitable[bool]]


@dataclass(slots=True)
class SweepStats:
    sources: int = 0
    baseline: int = 0
    unchanged: int = 0
    changed: int = 0
    blocked: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "baseline": self.baseline,
            "unchanged": self.unchanged,
            "changed": self.changed,
            "blocked": self.blocked,
            "errors": self.errors,
        }


@dataclass(frozen=True, slots=True)
class RegisteredCompetitor:
    competitor: CompetitorRow
    sources: tuple[SourceRow, ...]


@dataclass(frozen=True, slots=True)
class WeeklyReportResult:
    report: ReportRow
    line_sent: bool


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fetch_policy(source: SourceRow) -> FetchPolicy:
    return FetchPolicy(
        name=str(source.id),  # rate-limit bucket key
        tos_policy=source.tos_policy,
        rate_limit_per_hr=source.rate_limit_per_hr,
        enabled=source.enabled,
    )


def _clip_status(prefix: str, detail: str) -> str:
    return f"{prefix}{detail[:STATUS_DETAIL_MAX_CHARS]}"


class CompetitorIntelUseCases:
    def __init__(
        self,
        repo: CompetitorIntelRepository,
        audit: AuditWriter,
        *,
        storage: ObjectStorage,
        fetcher: Fetcher,
        analyst: ChangeAnalyst,
        line_push: LinePush | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._storage = storage
        self._fetcher = fetcher
        self._analyst = analyst
        self._line_push = line_push

    # ------------------------------------------------------------- registry

    async def register_competitor(
        self,
        *,
        name: str,
        kind: str | None,
        website: str | None,
        listing_urls: dict[str, object] | None,
        sources: Sequence[tuple[str, str]],
        actor: str,
    ) -> RegisteredCompetitor:
        """Create a competitor plus its monitored sources.

        `sources` is (type, url) pairs; a competitor with a website but no
        explicit sources gets an automatic 'website' source. EVERY source URL
        passes the §8.4 blocklist check BEFORE anything is written.
        """
        source_specs = list(sources)
        if not source_specs and website:
            source_specs = [("website", website)]
        for type_, url in source_specs:
            if type_ not in SOURCE_TYPES:
                raise ComplianceRefusedError("invalid_type", f"source type {type_!r} not allowed")
            check_url_compliance(url)

        competitor = await self._repo.create_competitor(
            name=name, kind=kind, website=website, listing_urls=listing_urls
        )
        created = [await self._create_source(competitor, type_, url) for type_, url in source_specs]
        await self._audit.write(
            actor,
            "competitor.registered",
            "competitors",
            competitor.id,
            {"name": name, "sources": [url for _, url in source_specs]},
        )
        return RegisteredCompetitor(competitor=competitor, sources=tuple(created))

    async def add_source(
        self,
        competitor_id: uuid.UUID,
        *,
        type: str,
        url: str,
        actor: str,  # noqa: A002
    ) -> SourceRow:
        competitor = await self._repo.get_competitor(competitor_id)
        if competitor is None:
            raise NotFoundError("competitor", competitor_id)
        if type not in SOURCE_TYPES:
            raise ComplianceRefusedError("invalid_type", f"source type {type!r} not allowed")
        check_url_compliance(url)
        source = await self._create_source(competitor, type, url)
        await self._audit.write(
            actor,
            "source.registered",
            "sources",
            source.id,
            {"competitor_id": str(competitor_id), "type": type, "url": url},
        )
        return source

    async def remove_source(
        self, competitor_id: uuid.UUID, source_id: uuid.UUID, actor: str
    ) -> None:
        source = await self._repo.get_source(source_id)
        if source is None or source.competitor_id != competitor_id:
            raise NotFoundError("source", source_id)
        await self._repo.delete_source(source_id)
        await self._audit.write(
            actor,
            "source.removed",
            "sources",
            source_id,
            {"competitor_id": str(competitor_id)},
        )

    async def _create_source(self, competitor: CompetitorRow, type_: str, url: str) -> SourceRow:
        return await self._repo.create_source(
            name=f"{competitor.name}:{type_}",
            type=type_,
            url=url,
            competitor_id=competitor.id,
            rate_limit_per_hr=DEFAULT_RATE_LIMIT_PER_HR,
            tos_policy="allowed",
            robots_ok=True,
            enabled=True,
        )

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
                logger.warning("sweep_source_failed", source_id=str(source.id), error=str(exc))
                stats.errors += 1
                await self._repo.set_source_result(
                    source.id, _clip_status("error: ", str(exc)), datetime.now(UTC)
                )
        await self._audit.write(
            actor, "competitors.swept", "competitors", competitor_id, stats.as_dict()
        )
        return stats.as_dict()

    async def _sweep_source(self, source: SourceDisplayRow, stats: SweepStats) -> None:
        assert source.competitor_id is not None  # sweep_sources filters these
        assert source.url is not None
        now = datetime.now(UTC)

        try:
            raw = await self._fetcher.fetch(_fetch_policy(source), source.url)
            text = rss_to_text(raw) if source.type == "rss" else html_to_text(raw)
        except ComplianceRefusedError as exc:
            logger.info("sweep_fetch_blocked", source_id=str(source.id), reason=exc.reason)
            stats.blocked += 1
            await self._repo.set_source_result(
                source.id, _clip_status("blocked: ", exc.reason), now
            )
            return
        except Exception as exc:  # noqa: BLE001 - fetch/parse errors are per-source
            logger.warning("sweep_fetch_error", source_id=str(source.id), error=str(exc))
            stats.errors += 1
            await self._repo.set_source_result(source.id, _clip_status("error: ", str(exc)), now)
            return

        content_hash = _content_hash(text)
        previous = await self._repo.latest_snapshot(source.competitor_id, source.id)

        if previous is not None and previous.content_hash == content_hash:
            # Short-circuit BEFORE any storage write: nothing changed.
            stats.unchanged += 1
            await self._repo.set_source_result(source.id, "unchanged", now)
            return

        storage_key = (
            f"snapshots/{source.competitor_id}/{source.id}/"
            f"{now.strftime('%Y-%m-%dT%H%M%S')}-{content_hash[:8]}.txt"
        )
        await self._storage.put(storage_key, text.encode("utf-8"), "text/plain; charset=utf-8")
        snapshot = await self._repo.create_snapshot(
            competitor_id=source.competitor_id,
            source_id=source.id,
            content_hash=content_hash,
            storage_key=storage_key,
        )

        if previous is None:
            # First snapshot: baseline marker only — deliberately NO change
            # event and NO LLM call (there is nothing to compare against).
            stats.baseline += 1
            await self._repo.set_source_result(source.id, "baseline", now)
            return

        previous_text = (await self._storage.get(previous.storage_key)).decode("utf-8")
        diff = diff_texts(previous_text, text)
        analysis = await self._analyst.classify(diff.excerpt, source.competitor_name or source.name)
        if analysis is not None:
            category, severity, summary = analysis.category, analysis.severity, analysis.summary
        else:
            category, severity = classify_change(diff)
            summary = fallback_summary(diff)
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

    async def compose_weekly_draft(self, now: datetime | None = None) -> tuple[str, str, int]:
        """Deterministic weekly draft: (draft, period, event_count). No writes.

        Window: the last Bangkok week — from Monday 00:00 of the previous week
        (week_start_bangkok - 7 days) up to now, so the Monday 08:00 beat run
        reports on the week that just ended and ad-hoc runs include fresh
        events. The report period is the ISO week of the window start. Split
        out in M4 so the analytics agent owns the LLM-upgrade step.
        """
        now = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
        since = week_start_bangkok(now) - timedelta(days=WEEKLY_REPORT_DAYS)
        iso_year, iso_week, _ = since.date().isocalendar()
        period = f"{iso_year}-W{iso_week:02d}"

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
        draft = compose_weekly_report(since.date(), now.date(), events)
        return draft, period, len(events)

    async def upgrade_weekly_draft(self, draft: str) -> str:
        """LLM upgrade with the never-raise fallback contract."""
        try:
            body = await self._analyst.upgrade_weekly_report(draft)
        except Exception:  # noqa: BLE001 - contract says never raise; belt-and-braces
            logger.exception("weekly_report_upgrade_failed")
            body = draft
        return body or draft

    async def deliver_weekly(
        self,
        actor: str,
        body: str,
        *,
        period: str,
        events: int,
        now: datetime | None = None,
    ) -> WeeklyReportResult:
        """Push to LINE (clipped, best-effort) then store + audit the report."""
        now = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
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
            period=period,
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
                "period": period,
                "events": events,
                "line_sent": line_sent,
            },
        )
        return WeeklyReportResult(report=report, line_sent=line_sent)

    async def generate_weekly_report(
        self, actor: str, now: datetime | None = None
    ) -> WeeklyReportResult:
        """Compose (deterministic Thai draft) -> LLM upgrade -> store + LINE.

        One-shot M3 behavior, now composed from the M4 split steps.
        """
        now = (now or datetime.now(BANGKOK_TZ)).astimezone(BANGKOK_TZ)
        draft, period, event_count = await self.compose_weekly_draft(now)
        body = await self.upgrade_weekly_draft(draft)
        return await self.deliver_weekly(actor, body, period=period, events=event_count, now=now)


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
