"""Celery worker + beat schedule (M1 + M2 + M3).

Production tasks:
- sync_bank_alerts    — poll Gmail for Thai bank alerts every 2 h (skips cleanly
                        when Gmail credentials are unset)
- send_daily_snapshot — 07:30 Asia/Bangkok Thai snapshot, stored + pushed to LINE
- process_document    — M2 KB ingestion pipeline (parse -> chunk -> index),
                        dispatched per upload by POST /v1/kb/documents
- consolidate_memories — Sun 03:00 Asia/Bangkok memory merge + expiry (§13)
- sweep_all_competitors — 06:00 Asia/Bangkok daily competitor-source sweep (M3)
- sweep_competitor    — one-competitor sweep, dispatched by POST
                        /v1/competitors/{id}:check
- weekly_competitor_report — Mon 08:00 Asia/Bangkok Thai competitor report

Tasks are sync Celery functions wrapping the async use cases with asyncio.run;
each run builds and disposes its own engine so worker processes never leak
connections across task invocations. Gateway adapters come from the shared
build_kb_adapters / build_competitor_adapters helpers
(src/infrastructure/adapters.py).
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
from src.application.memory import MemoryUseCases
from src.application.renovation import RenovationUseCases
from src.application.snapshot import DailySnapshotUseCases
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
    MemorySqlRepository,
    RenovationSqlRepository,
    SnapshotSqlRepository,
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


async def _send_daily_snapshot() -> dict[str, object]:
    settings = get_settings()
    line = LineClient(settings.line_channel_access_token, settings.line_owner_user_id)
    engine = build_engine(settings.database_url)
    try:
        maker = build_sessionmaker(engine)
        async with maker() as session:
            use_cases = DailySnapshotUseCases(
                SnapshotSqlRepository(session),
                SqlAuditWriter(session),
                line_push=line.push_text if line.is_configured else None,
            )
            result = await use_cases.generate(WORKER_ACTOR)
            await session.commit()
    finally:
        await engine.dispose()
    logger.info("daily_snapshot_done", report_id=str(result.report.id), line_sent=result.line_sent)
    return {"report_id": str(result.report.id), "line_sent": result.line_sent}


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


async def _consolidate_memories() -> dict[str, int]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    adapters = build_kb_adapters(settings)
    try:
        maker = build_sessionmaker(engine)
        async with maker() as session:
            use_cases = MemoryUseCases(
                MemorySqlRepository(session),
                SqlAuditWriter(session),
                vector_index=adapters.vector_index,
                embedder=adapters.embedder,
            )
            result = await use_cases.consolidate(WORKER_ACTOR)
            await session.commit()
    finally:
        await engine.dispose()
    logger.info("consolidate_memories_done", merged=result.merged, expired=result.expired)
    return {"merged": result.merged, "expired": result.expired}


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


async def _weekly_competitor_report() -> dict[str, object]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = build_sessionmaker(engine)
    adapters = build_competitor_adapters(settings, maker)
    try:
        async with maker() as session:
            use_cases = _competitor_use_cases(session, adapters, with_line=True)
            result = await use_cases.generate_weekly_report(WORKER_ACTOR)
            await session.commit()
    finally:
        await adapters.aclose()
        await engine.dispose()
    logger.info(
        "weekly_competitor_report_done",
        report_id=str(result.report.id),
        line_sent=result.line_sent,
    )
    return {"report_id": str(result.report.id), "line_sent": result.line_sent}


@celery_app.task(name="src.worker.sync_bank_alerts", bind=True, max_retries=3)
def sync_bank_alerts(self) -> dict[str, int]:  # noqa: ANN001 - celery bind
    try:
        return asyncio.run(_sync_bank_alerts())
    except Exception as exc:  # transient Gmail/DB failures retry with backoff
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc


@celery_app.task(name="src.worker.send_daily_snapshot", bind=True, max_retries=3)
def send_daily_snapshot(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    try:
        return asyncio.run(_send_daily_snapshot())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc


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


@celery_app.task(name="src.worker.consolidate_memories", bind=True, max_retries=3)
def consolidate_memories(self) -> dict[str, int]:  # noqa: ANN001 - celery bind
    try:
        return asyncio.run(_consolidate_memories())
    except Exception as exc:  # transient DB failures retry with backoff
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc


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


@celery_app.task(name="src.worker.weekly_competitor_report", bind=True, max_retries=3)
def weekly_competitor_report(self) -> dict[str, object]:  # noqa: ANN001 - celery bind
    try:
        return asyncio.run(_weekly_competitor_report())
    except Exception as exc:  # transient DB failures retry with backoff
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc
