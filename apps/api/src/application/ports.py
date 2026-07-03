"""Gateway ports for the knowledge base, memory (M2) and competitor intel (M3).

The application layer owns these Protocols; infrastructure supplies the
MinIO/Meilisearch/Qdrant/bge-m3/Anthropic implementations and tests supply
in-memory fakes (tests/fakes.py). Database repositories stay in
src/application/repositories.py — these are the non-database gateways.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Extracted document text plus whether OCR was needed to obtain it."""

    text: str
    ocr_used: bool = False


# Synchronous (data, mime) -> ParseResult; potentially slow (OCR), so the
# use case runs it in a worker thread via asyncio.to_thread.
TextExtractor = Callable[[bytes, str], ParseResult]


@dataclass(frozen=True, slots=True)
class KeywordChunk:
    """One chunk as sent to the keyword index."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    lang: str | None
    seq: int
    text: str


@dataclass(frozen=True, slots=True)
class VectorPoint:
    id: str
    vector: Sequence[float]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def presign(self, key: str, expires_seconds: int = 3600) -> str: ...


class KeywordIndex(Protocol):
    async def index_chunks(self, chunks: Sequence[KeywordChunk]) -> None: ...
    async def delete_document(self, document_id: uuid.UUID) -> None: ...

    async def search(self, q: str, limit: int) -> list[str]:
        """Return chunk ids, best match first."""
        ...


class VectorIndex(Protocol):
    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None: ...
    async def delete_document(self, collection: str, document_id: uuid.UUID) -> None: ...
    async def delete_points(self, collection: str, ids: Sequence[str]) -> None: ...
    async def search(
        self, collection: str, vector: Sequence[float], limit: int
    ) -> list[VectorHit]: ...


class Embedder(Protocol):
    @property
    def is_available(self) -> bool:
        """False when the ml extra (sentence-transformers) is not installed."""
        ...

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


# -------------------------------------------------- M3: competitor-intel ports


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """Per-source fetch policy handed to the Fetcher (mirrors the sources row).

    Mirrors collectors.compliance.SourcePolicy without importing collectors:
    the application layer stays importable when the optional collectors
    package is absent; the infrastructure adapter converts lazily.
    """

    name: str  # rate-limit bucket key (the source id)
    tos_policy: str  # 'allowed' | 'review' | 'prohibited'
    rate_limit_per_hr: int
    enabled: bool = True


class Fetcher(Protocol):
    """Compliance-gated outbound HTTP — the ONLY path a sweep may fetch through.

    Production: infrastructure.adapters.ComplianceGateFetcher wrapping
    collectors.compliance.ComplianceGate (robots.txt + rate limit + blocklist).
    Raises application.errors.ComplianceRefusedError when the gate refuses;
    any other exception is a plain fetch error.
    """

    async def fetch(self, policy: FetchPolicy, url: str) -> str: ...


@dataclass(frozen=True, slots=True)
class WeeklyReportEvent:
    """One change event as fed to the weekly-report composer/LLM."""

    competitor_name: str
    category: str
    severity: str
    summary: str
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeClassification:
    """LLM (or fallback) judgment on one competitor page diff."""

    category: str  # pricing|promotion|content|listing|other
    severity: str  # low|medium|high|critical
    summary: str  # Thai, <=160 chars


class ChangeAnalyst(Protocol):
    """LLM gateway for competitor intel.

    classify returns None when the LLM is unavailable, over budget, or its
    response is unusable — the caller falls back to the rule-based classifier.
    upgrade_weekly_report NEVER raises and returns the draft unchanged on any
    failure. Implementations record every real API attempt in agent_runs.
    """

    async def classify(self, diff: str, competitor_name: str) -> ChangeClassification | None: ...

    async def upgrade_weekly_report(self, draft: str) -> str: ...
