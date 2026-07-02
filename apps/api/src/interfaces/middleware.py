"""Request-id binding, access logging, and Prometheus instrumentation."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = structlog.get_logger("api.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - start
            # Prefer the route template over the raw path to keep label cardinality bounded.
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(duration)
            logger.info(
                "http_request",
                method=request.method,
                path=path,
                status=status,
                duration_ms=round(duration * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
