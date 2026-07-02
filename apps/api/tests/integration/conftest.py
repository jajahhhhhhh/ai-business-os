"""Integration fixtures: real PostgreSQL via DATABASE_URL, ASGI-level httpx.

These tests are gated: without DATABASE_URL they are skipped, never faked.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _async_url(url: str) -> str:
    """Accept plain postgres URLs and upgrade them to the asyncpg driver."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    from src.config import Settings
    from src.infrastructure.models import Base
    from src.main import create_app

    settings = Settings(database_url=_async_url(DATABASE_URL), env="dev")
    application = create_app(settings)

    # Ensure schema exists (idempotent; production uses `alembic upgrade head`).
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def seeded_lead(app: FastAPI) -> uuid.UUID:
    """Insert a lead directly (there is no POST /v1/leads endpoint in M0)."""
    from src.infrastructure.models import Lead

    unique = uuid.uuid4().hex
    async with app.state.sessionmaker() as session:
        lead = Lead(
            kind="guest",
            name=f"Integration Lead {unique}",
            intent_score=64,
            stage="discovered",
            dedup_hash=unique,
        )
        session.add(lead)
        await session.commit()
        return lead.id
