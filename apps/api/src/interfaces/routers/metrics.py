"""Prometheus scrape endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from src.infrastructure.metrics import render_metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
