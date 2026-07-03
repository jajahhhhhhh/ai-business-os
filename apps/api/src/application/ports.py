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
from datetime import date, datetime
from decimal import Decimal
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


# --------------------------------------------------------------- M3: LLM port


@dataclass(frozen=True, slots=True)
class ChangeAnalysis:
    """LLM judgment on one competitor page diff (summary in Thai)."""

    summary_th: str
    category: str  # pricing|promotion|content|availability|reviews|other
    severity: str  # low|medium|high|critical
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class WeeklyReportEvent:
    """One change event as fed to the weekly-report composer/LLM."""

    competitor_name: str
    category: str
    severity: str
    summary: str
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class WeeklyReportContext:
    period_start: date
    period_end: date
    # Deterministic Thai template (application/competitor_report.py) — the
    # LLM upgrades it to an executive version; callers fall back to it as-is.
    template_report: str
    events: tuple[WeeklyReportEvent, ...]


@dataclass(frozen=True, slots=True)
class ReportText:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


class ChangeAnalyst(Protocol):
    """LLM gateway for competitor intel. None results mean "unavailable or
    over budget" — callers must fall back to the rule-based path."""

    @property
    def is_available(self) -> bool:
        """False when no API key is configured (NullChangeAnalyst)."""
        ...

    async def analyze_change(
        self, competitor_name: str, url: str, diff_excerpt: str
    ) -> ChangeAnalysis | None: ...

    async def compose_weekly_report(self, context: WeeklyReportContext) -> ReportText | None: ...
