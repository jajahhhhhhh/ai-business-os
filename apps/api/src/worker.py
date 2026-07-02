"""Celery worker + beat schedule (M1).

Two production tasks:
- sync_bank_alerts   — poll Gmail for Thai bank alerts every 2 h (skips cleanly
                       when Gmail credentials are unset)
- send_daily_snapshot — 07:30 Asia/Bangkok Thai snapshot, stored + pushed to LINE

Tasks are sync Celery functions wrapping the async use cases with asyncio.run;
each run builds and disposes its own engine so worker processes never leak
connections across task invocations.
"""

from __future__ import annotations

import asyncio

import structlog
from celery import Celery
from celery.schedules import crontab

from src.application.bank_transactions import BankTransactionUseCases
from src.application.errors import UnrecognizedBankAlertError
from src.application.renovation import RenovationUseCases
from src.application.snapshot import DailySnapshotUseCases
from src.config import get_settings
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.db import build_engine, build_sessionmaker
from src.infrastructure.gmail import GmailClient
from src.infrastructure.line import LineClient
from src.infrastructure.repositories import (
    BankTransactionSqlRepository,
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
    logger.info(
        "daily_snapshot_done", report_id=str(result.report.id), line_sent=result.line_sent
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
