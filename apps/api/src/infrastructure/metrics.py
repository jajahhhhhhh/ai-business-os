"""Prometheus metrics registry for the API service."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["method", "path", "status"],
)

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


def render_metrics() -> tuple[bytes, str]:
    """Return (payload, content_type) in Prometheus text exposition format."""
    return generate_latest(), CONTENT_TYPE_LATEST
