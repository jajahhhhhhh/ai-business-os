"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from src.config import Settings, get_settings
from src.infrastructure.adapters import KbAdapters, build_kb_adapters
from src.infrastructure.db import build_engine, build_sessionmaker
from src.interfaces.dependencies import require_principal
from src.interfaces.middleware import RequestContextMiddleware
from src.interfaces.problems import register_exception_handlers
from src.interfaces.routers import (
    agents,
    competitors,
    health,
    jobs,
    kb,
    leads,
    memory,
    metrics,
    renovation,
    reports,
)
from src.logging_setup import configure_logging


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.engine.dispose()


def create_app(
    settings: Settings | None = None, *, kb_adapters: KbAdapters | None = None
) -> FastAPI:
    """Build the app. `kb_adapters` is the M2 test seam: integration tests
    inject in-memory fakes (tests/fakes.py) so they run with only PostgreSQL
    available; production wiring comes from build_kb_adapters(settings)."""
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="AI Business OS API",
        version=settings.version,
        docs_url="/docs" if settings.env == "dev" else None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    # The engine is lazy (no connection until first use), so building it here
    # keeps request dependencies simple even when the lifespan never runs.
    app.state.engine = build_engine(settings.database_url)
    app.state.sessionmaker = build_sessionmaker(app.state.engine)
    app.state.kb_adapters = kb_adapters or build_kb_adapters(settings)

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    # Unauthenticated probes.
    app.include_router(health.router, prefix="/v1")
    app.include_router(metrics.router, prefix="/v1")

    # Business routers behind the API-key seam (bypassed when ENV=dev).
    auth = [Depends(require_principal)]
    app.include_router(renovation.router, prefix="/v1", dependencies=auth)
    app.include_router(leads.router, prefix="/v1", dependencies=auth)
    app.include_router(competitors.router, prefix="/v1", dependencies=auth)
    app.include_router(agents.router, prefix="/v1", dependencies=auth)
    app.include_router(reports.router, prefix="/v1", dependencies=auth)
    app.include_router(jobs.router, prefix="/v1", dependencies=auth)
    app.include_router(kb.router, prefix="/v1", dependencies=auth)
    app.include_router(memory.router, prefix="/v1", dependencies=auth)

    return app


app = create_app()
