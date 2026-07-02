"""Liveness and readiness probes."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.interfaces.dependencies import SettingsDep
from src.interfaces.schemas import DependencyStatus, HealthOut, ReadyOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(settings: SettingsDep) -> HealthOut:
    return HealthOut(status="ok", version=settings.version, env=settings.env)


@router.get("/health/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
async def ready(request: Request) -> JSONResponse:
    """Readiness: checks each hard dependency and never raises."""
    checks: dict[str, DependencyStatus] = {}

    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        checks["database"] = DependencyStatus(status="up")
    except Exception as exc:  # noqa: BLE001 - readiness must report, not crash
        checks["database"] = DependencyStatus(status="down", detail=str(exc))

    degraded = any(check.status != "up" for check in checks.values())
    body = ReadyOut(status="degraded" if degraded else "ok", checks=checks)
    return JSONResponse(status_code=503 if degraded else 200, content=body.model_dump())
