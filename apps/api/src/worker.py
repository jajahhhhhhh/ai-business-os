"""Celery worker + beat schedule (M1 + M2 + M3 + M4 agents).

Production tasks:
- sync_bank_alerts    — poll Gmail for Thai bank alerts every 2 h (skips cleanly
                        when Gmail credentials are unset)
- send_daily_snapshot — 07:30 Asia/Bangkok; since M4 the body runs the
                        ANALYTICS agent ('daily-snapshot') — task name stable
- process_document    — M2 KB ingestion pipeline (parse -> chunk -> index),
                        dispatched per upload by POST /v1/kb/documents
- consolidate_memories — Sun 03:00 Asia/Bangkok; routes through the MEMORY
                        agent ('consolidate') since M4 — task name stable
- sweep_all_competitors — 06:00 Asia/Bangkok daily competitor-source sweep (M3)
- sweep_competitor    — one-competitor sweep, dispatched by POST
                        /v1/competitors/{id}:check
- weekly_competitor_report — Mon 08:00 Asia/Bangkok; since M4 the body runs
                        the ANALYTICS agent ('weekly-competitor')
- run_agent_task      — generic M4 agent runner: (agent_name, task_kind).
                        Beat: memory capture-signals 07:00 daily, planner
                        weekly-plan Mon 08:30, qa evaluate Sun 04:30.
- collect_lead_source — M5: one lead source through the customer-discovery
                        agent ('discover'), dispatched by POST
                        /v1/sources/{id}:collect
- collect_all_lead_sources — M5: every enabled lead source every 4 h (§13)
                        via the customer-discovery agent ('discover-all')
- cluster_leads       — M5: Sun 05:30 greedy lead clustering (skips cleanly
                        without the ml extra)
- anonymize_stale_leads — M5: Sun 05:45 PDPA retention pass (§8.5, 18 months)

Tasks are sync Celery functions wrapping the async use cases with asyncio.run;
each run builds and disposes its own engine so worker processes never leak
connections across task invocations. Gateway adapters come from the shared
build_kb_adapters / build_competitor_adapters helpers
(src/infrastructure/adapters.py). The orchestrator-backed agent runtime is
imported lazily inside the task bodies (collectors pattern) so this module
stays importable when the orchestrator package is absent.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from celery import Celery
from celery.schedules import crontab
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.bank_transactions import BankTransactionUseCases
from src.application.competitor_intel import CompetitorIntelUseCases
from src.application.errors import UnrecognizedBankAlertError
from src.application.kb import ERROR_MAX_CHARS, KnowledgeBaseUseCases
from src.application.renovation import RenovationUseCases
from src.config import get_settings
from src.infrastructure.adapters import (
    CompetitorAdapters,
    KbAdapters,
    build_competitor_adapters,
    build_kb_adapters,
)
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.db import build_engine, build_sessionmaker
from src.infrastructure.gmail import GmailClient
from src.infrastructure.line import LineClient
from src.infrastructure.repositories import (
    BankTransactionSqlRepository,
    CompetitorIntelSqlRepository,
    KnowledgeBaseSqlRepository,
    RenovationSqlRepository,
)
from src.logging_setup import configure_logging

logger = structlog.get_logger("worker")

_settings = get_settings()
configure_logging(_settings)

celery_app = Celery(
    "aibos",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    timezone="Asia/Bangkok",
    enable_utc=True,
)
celery_app.conf.beat_schedule = {
    "sync-bank-alerts-every-2h": {
        "task": "src.worker.sync_bank_alerts",
        "schedule": crontab(minute=0, hour="*/2"),
    },
    "daily-snapshot-0730": {
        "task": "src.worker.send_daily_snapshot",
        "schedule": crontab(minute=30, hour=7),
    },
    # ARCHITECTURE.md §13: memory consolidation Sun 03:00 Asia/Bangkok.
    "consolidate-memories-sun-0300": {
        "task": "src.worker.consolidate_memories",
        "schedule": crontab(minute=0, hour=3, day_of_week="sun"),
    },
    # M3: daily competitor sweep 06:00 Asia/Bangkok.
    "sweep-all-competitors-0600": {
        "task": "src.worker.sweep_all_competitors",
        "schedule": crontab(minute=0, hour=6),
    },
    # M3: weekly Thai competitor report Mon 08:00 Asia/Bangkok.
    "weekly-competitor-report-mon-0800": {
        "task": "src.worker.weekly_competitor_report",
        "schedule": crontab(minute=0, hour=8, day_of_week="mon"),
    },
    # M4: memory agent captures high-severity competitor signals daily 07:00.
    "memory-capture-signals-0700": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=0, hour=7),
        "args": ("memory", "capture-signals"),
    },
    # M4: planner weekly Thai plan Mon 08:30 Asia/Bangkok.
    "planner-weekly-plan-mon-0830": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=30, hour=8, day_of_week="mon"),
        "args": ("planner", "weekly-plan"),
    },
    # M4: qa evaluation sweep Sun 04:30 Asia/Bangkok (§13 prompt/eval slot).
    "qa-evaluate-sun-0430": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=30, hour=4, day_of_week="sun"),
        "args": ("qa", "evaluate"),
    },
    # M5: lead-source collector sweep every 4 h (§13).
    "collect-all-lead-sources-4h": {
        "task": "src.worker.collect_all_lead_sources",
        "schedule": crontab(minute=0, hour="*/4"),
    },
    # M5: weekly lead clustering Sun 05:30 Asia/Bangkok.
    "cluster-leads-sun-0530": {
        "task": "src.worker.cluster_leads",
        "schedule": crontab(minute=30, hour=5, day_of_week="sun"),
    },
    # M5: PDPA retention pass Sun 05:45 Asia/Bangkok (§8.5, 18 months).
    "anonymize-stale-leads-sun-0545": {
        "task": "src.worker.anonymize_stale_leads",
        "schedule": crontab(minute=45, hour=5, day_of_week="sun"),
    },
    # M6 marketing pipeline (weekly, staggered so each stage's inputs exist):
    # SEO brief Tue 09:00 -> content draft Wed 09:00 -> content calendar Thu 09:00.
    "seo-brief-tue-0900": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=0, hour=9, day_of_week="tue"),
        "args": ("seo", "seo-brief"),
    },
    "content-draft-wed-0900": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=0, hour=9, day_of_week="wed"),
        "args": ("content", "content-draft"),
    },
    "content-calendar-thu-0900": {
        "task": "src.worker.run_agent_task",
        "schedule": crontab(minute=0, hour=9, day_of_week="thu"),
        "args": ("social", "content-calendar"),
    },
}

WORKER_ACTOR = "worker"


async def _sync_bank_alerts() -> dict[str, int]:
    settings = get_settings()
    gmail = GmailClient(
        settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token
    )
    if not gmail.is_configured:
        logger.info("sync_bank_alerts_skipped", reason="gmail not configured")
        return {"fetched": 0, "ingested": 0, "duplicates": 0, "unrecognized": 0}

    messages = await gmail.fetch_messages()
    counts = {"fetched": len(messages), "ingested": 0, "duplicates": 0, "unrecognized": 0}

    engine = build_engine(settings.database_url)
    try:
        maker = build_sessionmaker(engine)
        for message in messages:
            # One session per message: a bad alert must not roll back the batch.
            async with maker() as session:
                audit = SqlAuditWriter(session)
                use_cases = BankTransactionUseCases(
                    BankTransactionSqlRepository(session),
                    audit,
                    RenovationUseCases(RenovationSqlRepository(session), audit),
                )
                try:
                    result = await use_cases.ingest_alert(
                        message.body_text, source="gmail", actor=WORKER_ACTOR
                    )
                    await session.commit()
                    counts["ingested" if result.created else "duplicates"] += 1
                except UnrecognizedBankAlertError:
                    await session.rollback()
                    counts["unrecognized"] += 1
    finally:
        await engine.dispose()
    logger.info("sync_bank_alerts_done", **counts)
    return counts


# ---------------------------------------------------------------- M4: agents


async def _run_agent(
    agent_name: str, task_kind: str, payload: dict[str, object] | None = None
) -> dict[str, object]:
    """Run one agent task with per-run engine/adapters/runtime; NEVER raises
    (run_agent itself absorbs everything; this adds setup/teardown safety).

    The agent runtime import is lazy (collectors pattern) so the worker module
    imports cleanly without the orchestrator package; the task then reports a
    failed status instead of crashing the worker.
    """
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = build_sessionmaker(engine)
    competitor_adapters = build_competitor_adapters(settings, maker)
    runtime = None
    try:
        from src.infrastructure.agent_runtime import build_agent_runtime, run_agent

        runtime = build_agent_runtime(settings, maker)
        return await run_agent(
            agent_name,
            task_kind,
            settings=settings,
            maker=maker,
            runtime=runtime,
            kb_adapters=build_kb_adapters(settings),
            competitor_adapters=competitor_adapters,
            actor=WORKER_ACTOR,
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 - never raise out of a worker task
        logger.exception("run_agent_setup_failed", agent=agent_name, task_kind=task_kind)
        return {
            "agent": agent_name,
            "task_kind": task_kind,
            "run_id": None,
            "status": "failed",
            "error": str(exc)[:ERROR_MAX_CHARS],
            "outputs": [],
        }
    finally:
        if runtime is not None:
            await runtime.aclose()
        await competitor_adapters.aclose()
        await engine.dispose()


# --------------------------------------------------------------------- M2: KB


def _kb_use_cases(session: AsyncSession, adapters: KbAdapters) -> KnowledgeBaseUseCases:
    return KnowledgeBaseUseCases(
        KnowledgeBaseSqlRepository(session),
        SqlAuditWriter(session),
        storage=adapters.storage,
        keyword_index=adapters.keyword_index,
        vector_index=adapters.vector_index,
        embedder=adapters.embedder,
        extract=adapters.extract,
    )


async def run_document_pipeline(
    document_id: uuid.UUID,
    *,
    maker: async_sessionmaker[AsyncSession],
    adapters: KbAdapters,
) -> dict[str, str]:
    """Run the KB pipeline for one document; NEVER raises.

    On failure the pipeline transaction is rolled back and status='failed'
    (error truncated to ERROR_MAX_CHARS) is persisted in a FRESH session — the
    failed transaction may be unusable. Shared by the Celery task and the
    BackgroundTasks fallback in the kb router.
    """
    error: str
    async with maker() as session:
        try:
            document = await _kb_use_cases(session, adapters).process_document(
                document_id, actor=WORKER_ACTOR
            )
            await session.commit()
            logger.info("process_document_done", document_id=str(document_id))
            return {"document_id": str(document_id), "status": document.status}
        except Exception as exc:  # noqa: BLE001 - recorded on the row below
            await session.rollback()
            logger.warning("process_document_failed", document_id=str(document_id), error=str(exc))
            error = str(exc)[:ERROR_MAX_CHARS] or exc.__class__.__name__
    try:
        async with maker() as session:
            repo = KnowledgeBaseSqlRepository(session)
            await repo.update_document(document_id, {"status": "failed", "error": error})
            await SqlAuditWriter(session).write(
                WORKER_ACTOR, "kb.document_failed", "documents", document_id, {"error": error}
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - DB unusable; the row keeps its last status
        logger.exception("process_document_status_write_failed", document_id=str(document_id))
    return {"document_id": str(document_id), "status": "failed"}


async def _process_document(document_id: str) -> dict[str, str]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        return await run_document_pipeline(
            uuid.UUID(document_id),
            maker=build_sessionmaker(engine),
            adapters=build_kb_adapters(settings),
        )
    finally:
        await engine.dispose()


# -------------------------------------------------------- M3: competitor intel


def _competitor_use_cases(
    session: AsyncSession, adapters: CompetitorAdapters, *, with_line: bool = False
) -> CompetitorIntelUseCases:
    line_push = None
    if with_line:
        settings = get_settings()
        line = LineClient(settings.line_channel_access_token, settings.line_owner_user_id)
        line_push = line.push_text if line.is_configured else None
    return CompetitorIntelUseCases(
        CompetitorIntelSqlRepository(session),
        SqlAuditWriter(session),
        storage=adapters.storage,
        fetcher=adapters.fetcher,
        analyst=adapters.analyst,
        line_push=line_push,
    )


async def run_competitor_sweep(
    competitor_id: uuid.UUID | None,
    *,
    maker: async_sessionmaker[AsyncSession],
    adapters: CompetitorAdapters,
) -> dict[str, object]:
    """Sweep one competitor (or all when None); NEVER raises.

    Per-source failures are already absorbed inside the use case (recorded as
    'blocked: ...'/'error: ...' statuses); this guard additionally catches
    setup/DB failures so neither the Celery task nor the BackgroundTasks
    fallback can blow up. Shared by both dispatch paths (kb pattern).
    """
    try:
        async with maker() as session:
            use_cases = _competitor_use_cases(session, adapters)
            if competitor_id is None:
                stats = await use_cases.sweep_all(WORKER_ACTOR)
            else:
                stats = await use_cases.sweep_competitor(competitor_id, WORKER_ACTOR)
            await session.commit()
        logger.info("competitor_sweep_done", competitor_id=str(competitor_id), **stats)
        return {"status": "done", **stats}
    except Exception as exc:  # noqa: BLE001 - sweep must never raise out of a task
        logger.exception("competitor_sweep_failed", competitor_id=str(competitor_id))
        return {"status": "failed", "error": str(exc)[:ERROR_MAX_CHARS]}


async def _sweep_competitors(competitor_id: uuid.UUID | None) -> dict[str, object]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = build_sessionmaker(engine)
    adapters = build_competitor_adapters(settings, maker)
    try:
        return await run_competitor_sweep(competitor_id, maker=maker, adapters=adapters)
    finally:
        await adapters.aclose()
        await engine.dispose()


@celery_app.task(name="src.worker.sync_bank_alerts", bind=True, max_retries=3)
def sync_bank_alerts(self) -> dict[str, int]:  # noqa: ANN001 - celery bind
    try:
        return asyncio.run(_sync_bank_alerts())
    except Exception as exc:  # transient Gmail/DB failures retry with backoff
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc


@celery_app.task(name="src.worker.send_daily_snapshot", bind=True)
def send_daily_snapshot(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M4: the 07:30 snapshot runs the analytics agent (task name stable).
    No Celery retry: retries/escalation/parking are the Runner's job and
    _run_agent never raises."""
    try:
        return asyncio.run(_run_agent("analytics", "daily-snapshot"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("send_daily_snapshot_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.process_document", bind=True)
def process_document(self, document_id: str) -> dict[str, str]:  # noqa: ANN001 - celery bind
    """No retry: run_document_pipeline never raises — parse/index failures are
    recorded on the document row (status='failed') and must not raise out of
    the worker task."""
    try:
        return asyncio.run(_process_document(document_id))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("process_document_task_error", document_id=document_id)
        return {"document_id": document_id, "status": "failed"}


@celery_app.task(name="src.worker.consolidate_memories", bind=True)
def consolidate_memories(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M4: Sun 03:00 consolidation routes through the memory agent (task name
    stable; failure handling is the Runner's job)."""
    try:
        return asyncio.run(_run_agent("memory", "consolidate"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("consolidate_memories_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.sweep_competitor", bind=True)
def sweep_competitor(self, competitor_id: str) -> dict[str, object]:  # noqa: ANN001
    """No retry: run_competitor_sweep never raises — per-source failures are
    recorded on the source rows and must not raise out of the worker task."""
    try:
        return asyncio.run(_sweep_competitors(uuid.UUID(competitor_id)))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("sweep_competitor_task_error", competitor_id=competitor_id)
        return {"status": "failed"}


@celery_app.task(name="src.worker.sweep_all_competitors", bind=True)
def sweep_all_competitors(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """No retry: same never-raise contract as sweep_competitor."""
    try:
        return asyncio.run(_sweep_competitors(None))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("sweep_all_competitors_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.weekly_competitor_report", bind=True)
def weekly_competitor_report(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M4: Mon 08:00 weekly report runs the analytics agent (task name stable)."""
    try:
        return asyncio.run(_run_agent("analytics", "weekly-competitor"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("weekly_competitor_report_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.run_agent_task", bind=True)
def run_agent_task(self, agent_name: str, task_kind: str) -> dict[str, object]:  # noqa: ANN001
    """Generic M4 agent runner (beat + POST /v1/agents/{name}:trigger).

    No Celery retry: retry/escalate/park is the orchestrator Runner's job and
    _run_agent never raises."""
    try:
        return asyncio.run(_run_agent(agent_name, task_kind))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("run_agent_task_error", agent=agent_name, task_kind=task_kind)
        return {"agent": agent_name, "task_kind": task_kind, "status": "failed"}


# ---------------------------------------------------------- M5: lead discovery


async def _run_lead_maintenance(kind: str) -> dict[str, object]:
    """Run clustering or anonymization with a per-run engine; NEVER raises."""
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        from src.application.lead_maintenance import LeadMaintenanceUseCases
        from src.infrastructure.repositories import LeadMaintenanceSqlRepository

        maker = build_sessionmaker(engine)
        kb_adapters = build_kb_adapters(settings)
        async with maker() as session:
            use_cases = LeadMaintenanceUseCases(
                LeadMaintenanceSqlRepository(session),
                SqlAuditWriter(session),
                embedder=kb_adapters.embedder,
            )
            if kind == "cluster":
                result = await use_cases.cluster_leads(WORKER_ACTOR)
            else:
                result = await use_cases.anonymize_stale_leads(WORKER_ACTOR)
            await session.commit()
        logger.info("lead_maintenance_done", kind=kind, **result)
        return dict(result)
    except Exception as exc:  # noqa: BLE001 - maintenance must never crash the worker
        logger.exception("lead_maintenance_failed", kind=kind)
        return {"status": "failed", "error": str(exc)[:ERROR_MAX_CHARS]}
    finally:
        await engine.dispose()


@celery_app.task(name="src.worker.collect_lead_source", bind=True)
def collect_lead_source(self, source_id: str) -> dict[str, object]:  # noqa: ANN001
    """M5: one lead source through the customer-discovery agent ('discover').

    No Celery retry: per-source failures land in sources.last_status and
    retry/escalate/park is the Runner's job."""
    try:
        return asyncio.run(_run_agent("customer-discovery", "discover", {"source_id": source_id}))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("collect_lead_source_task_error", source_id=source_id)
        return {"status": "failed"}


@celery_app.task(name="src.worker.collect_all_lead_sources", bind=True)
def collect_all_lead_sources(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M5: 4-hourly lead-source sweep via customer-discovery ('discover-all')."""
    try:
        return asyncio.run(_run_agent("customer-discovery", "discover-all"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("collect_all_lead_sources_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.cluster_leads", bind=True)
def cluster_leads(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M5: Sun 05:30 greedy lead clustering (_run_lead_maintenance never raises)."""
    try:
        return asyncio.run(_run_lead_maintenance("cluster"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("cluster_leads_task_error")
        return {"status": "failed"}


@celery_app.task(name="src.worker.anonymize_stale_leads", bind=True)
def anonymize_stale_leads(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    """M5: Sun 05:45 PDPA retention pass (§8.5)."""
    try:
        return asyncio.run(_run_lead_maintenance("anonymize"))
    except Exception:  # noqa: BLE001 - defensive: even setup failures stay in-task
        logger.exception("anonymize_stale_leads_task_error")
        return {"status": "failed"}
