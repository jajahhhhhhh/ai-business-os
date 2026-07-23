"""In-memory fakes for the M2/M3 gateway ports (src/application/ports.py).

Shared by the unit tests and the DATABASE_URL-gated integration tests: the
integration suite runs with ONLY PostgreSQL available — MinIO, Meilisearch,
Qdrant, the compliance-gated fetcher and the Anthropic analyst are replaced
by these fakes via create_app(kb_adapters=..., competitor_adapters=...). The
real adapters are exercised against the VPS/CI docker-compose stack.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Sequence
from typing import Any

from src.application.ports import KeywordChunk, ParseResult, VectorHit, VectorPoint

EMBEDDING_DIM = 32


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def presign(self, key: str, expires_seconds: int = 3600) -> str:
        return f"https://fake-storage.local/{key}?expires={expires_seconds}"


class InMemoryKeywordIndex:
    """Naive substring-count relevance — good enough for deterministic tests,
    and substring matching works for Thai (no tokenization needed)."""

    def __init__(self) -> None:
        self.chunks: dict[str, KeywordChunk] = {}

    async def index_chunks(self, chunks: Sequence[KeywordChunk]) -> None:
        for chunk in chunks:
            self.chunks[str(chunk.id)] = chunk

    async def delete_document(self, document_id: uuid.UUID) -> None:
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }

    async def search(self, q: str, limit: int) -> list[str]:
        terms = [term for term in q.split() if term] or [q]
        scored: list[tuple[int, str]] = []
        for chunk_id, chunk in self.chunks.items():
            score = sum(chunk.text.count(term) for term in terms)
            if score > 0:
                scored.append((score, chunk_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [chunk_id for _, chunk_id in scored[:limit]]


class InMemoryVectorIndex:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, tuple[list[float], dict[str, Any]]]] = {}

    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None:
        store = self.collections.setdefault(collection, {})
        for point in points:
            store[point.id] = (list(point.vector), dict(point.payload))

    async def delete_document(self, collection: str, document_id: uuid.UUID) -> None:
        store = self.collections.get(collection, {})
        for point_id in [
            pid
            for pid, (_, payload) in store.items()
            if payload.get("document_id") == str(document_id)
        ]:
            del store[point_id]

    async def delete_points(self, collection: str, ids: Sequence[str]) -> None:
        store = self.collections.get(collection, {})
        for point_id in ids:
            store.pop(point_id, None)

    async def search(self, collection: str, vector: Sequence[float], limit: int) -> list[VectorHit]:
        store = self.collections.get(collection, {})
        hits = [
            VectorHit(id=point_id, score=_cosine(list(vector), stored), payload=payload)
            for point_id, (stored, payload) in store.items()
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.id))
        return hits[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _trigram_vector(text: str) -> list[float]:
    """Deterministic hashed character-trigram embedding: identical texts map
    to identical vectors, near-duplicates to nearby ones — enough to exercise
    real cosine-ranking behaviour for Thai and English without a model."""
    vector = [0.0] * EMBEDDING_DIM
    padded = f"  {text.lower()}  "
    for i in range(len(padded) - 2):
        trigram = padded[i : i + 3]
        digest = hashlib.md5(trigram.encode("utf-8")).digest()
        vector[digest[0] % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class FakeEmbedder:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls: list[list[str]] = []

    @property
    def is_available(self) -> bool:
        return self.available

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        assert self.available, "embed_texts called on an unavailable embedder"
        batch = [str(text) for text in texts]
        self.calls.append(batch)
        return [_trigram_vector(text) for text in batch]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]


class BrokenVectorIndex:
    """Every call raises — simulates Qdrant being down (NFR-1 paths)."""

    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None:
        raise ConnectionError("qdrant is down")

    async def delete_document(self, collection: str, document_id: uuid.UUID) -> None:
        raise ConnectionError("qdrant is down")

    async def delete_points(self, collection: str, ids: Sequence[str]) -> None:
        raise ConnectionError("qdrant is down")

    async def search(self, collection: str, vector: Sequence[float], limit: int) -> list[VectorHit]:
        raise ConnectionError("qdrant is down")


def fake_extract(data: bytes, mime: str) -> ParseResult:
    """Text-only extractor for tests (no parsing libraries needed)."""
    return ParseResult(text=data.decode("utf-8"), ocr_used=False)


class NullAuditWriter:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, str, uuid.UUID | None, dict[str, Any] | None]] = []

    async def write(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: uuid.UUID | None,
        diff: dict[str, Any] | None,
    ) -> None:
        self.entries.append((actor, action, entity, entity_id, diff))


# ---------------------------------------------------------------- fake repos
# Plain-object rows + dict-backed repositories satisfying the repository
# protocols, for unit-testing the use cases without a database.

from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402


@dataclass
class FakeDocumentRow:
    id: uuid.UUID
    title: str
    mime: str
    storage_key: str
    lang: str | None
    size_bytes: int | None
    source: str
    status: str = "pending"
    error: str | None = None
    ocr_done: bool = False
    meili_indexed: bool = False
    embedded: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeChunkRow:
    id: uuid.UUID
    document_id: uuid.UUID
    seq: int
    text: str
    qdrant_point_id: str | None = None


@dataclass
class FakeChunkHydrationRow:
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    seq: int
    text: str


class FakeKnowledgeBaseRepository:
    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, FakeDocumentRow] = {}
        self.chunks: dict[uuid.UUID, FakeChunkRow] = {}

    async def create_document(
        self,
        *,
        id: uuid.UUID,  # noqa: A002 - mirrors the protocol
        title: str,
        mime: str,
        storage_key: str,
        lang: str | None,
        size_bytes: int,
        source: str,
    ) -> FakeDocumentRow:
        row = FakeDocumentRow(
            id=id,
            title=title,
            mime=mime,
            storage_key=storage_key,
            lang=lang,
            size_bytes=size_bytes,
            source=source,
        )
        self.documents[id] = row
        return row

    async def get_document(self, document_id: uuid.UUID) -> FakeDocumentRow | None:
        return self.documents.get(document_id)

    async def list_documents(self, status: str | None, limit: int) -> list[FakeDocumentRow]:
        rows = [row for row in self.documents.values() if status is None or row.status == status]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[:limit]

    async def update_document(
        self, document_id: uuid.UUID, changes: dict[str, object]
    ) -> FakeDocumentRow:
        row = self.documents[document_id]
        for key, value in changes.items():
            setattr(row, key, value)
        return row

    async def replace_chunks(
        self, document_id: uuid.UUID, chunks: Sequence[tuple[int, str]]
    ) -> list[FakeChunkRow]:
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }
        rows = [
            FakeChunkRow(id=uuid.uuid4(), document_id=document_id, seq=seq, text=text)
            for seq, text in chunks
        ]
        for row in rows:
            self.chunks[row.id] = row
        return rows

    async def set_chunk_point_ids(self, chunk_ids: Sequence[uuid.UUID]) -> None:
        for chunk_id in chunk_ids:
            self.chunks[chunk_id].qdrant_point_id = str(chunk_id)

    async def chunk_count(self, document_id: uuid.UUID) -> int:
        return sum(1 for chunk in self.chunks.values() if chunk.document_id == document_id)

    async def get_chunks_with_titles(
        self, chunk_ids: Sequence[uuid.UUID]
    ) -> list[FakeChunkHydrationRow]:
        rows = []
        for chunk_id in chunk_ids:
            chunk = self.chunks.get(chunk_id)
            if chunk is None:
                continue
            document = self.documents.get(chunk.document_id)
            if document is None:
                continue
            rows.append(
                FakeChunkHydrationRow(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=document.title,
                    seq=chunk.seq,
                    text=chunk.text,
                )
            )
        return rows


@dataclass
class FakeMemoryRow:
    id: uuid.UUID
    kind: str
    subject: str
    body: str
    importance: int
    embedding_point_id: str | None = None
    expires_at: datetime | None = None
    consolidated_into: uuid.UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.memories: dict[uuid.UUID, FakeMemoryRow] = {}

    def _is_active(self, row: FakeMemoryRow, now: datetime) -> bool:
        return row.consolidated_into is None and (row.expires_at is None or row.expires_at > now)

    async def create(
        self,
        *,
        kind: str,
        subject: str,
        body: str,
        importance: int,
        expires_at: datetime | None,
        source_run_id: uuid.UUID | None,
    ) -> FakeMemoryRow:
        row = FakeMemoryRow(
            id=uuid.uuid4(),
            kind=kind,
            subject=subject,
            body=body,
            importance=importance,
            expires_at=expires_at,
        )
        self.memories[row.id] = row
        return row

    async def set_embedding_point(self, memory_id: uuid.UUID, point_id: str) -> FakeMemoryRow:
        row = self.memories[memory_id]
        row.embedding_point_id = point_id
        return row

    async def search_text(
        self, q: str, kind: str | None, limit: int, now: datetime
    ) -> list[FakeMemoryRow]:
        needle = q.lower()
        rows = [
            row
            for row in self.memories.values()
            if self._is_active(row, now)
            and (kind is None or row.kind == kind)
            and (needle in row.subject.lower() or needle in row.body.lower())
        ]
        # importance desc, then created_at desc — mirrors MemorySqlRepository.
        rows.sort(key=lambda row: row.created_at, reverse=True)
        rows.sort(key=lambda row: row.importance, reverse=True)
        return rows[:limit]

    async def get_active_many(
        self, memory_ids: Sequence[uuid.UUID], now: datetime
    ) -> list[FakeMemoryRow]:
        return [
            self.memories[memory_id]
            for memory_id in memory_ids
            if memory_id in self.memories and self._is_active(self.memories[memory_id], now)
        ]

    async def list_active(self, now: datetime) -> list[FakeMemoryRow]:
        return sorted(
            (row for row in self.memories.values() if self._is_active(row, now)),
            key=lambda row: row.created_at,
        )

    async def list_expired(self, now: datetime) -> list[FakeMemoryRow]:
        return [
            row
            for row in self.memories.values()
            if row.expires_at is not None and row.expires_at <= now
        ]

    async def mark_consolidated(
        self, memory_ids: Sequence[uuid.UUID], survivor_id: uuid.UUID
    ) -> None:
        for memory_id in memory_ids:
            self.memories[memory_id].consolidated_into = survivor_id

    async def delete_many(self, memory_ids: Sequence[uuid.UUID]) -> None:
        for memory_id in memory_ids:
            self.memories.pop(memory_id, None)


# ------------------------------------------------------- M3: competitor intel
# Fakes for the Fetcher/ChangeAnalyst ports, the RunRecorder budget seam and
# the CompetitorIntelRepository protocol (sweep state-machine unit tests).

from datetime import timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from src.application.ports import ChangeClassification, FetchPolicy  # noqa: E402

UPGRADE_ANALYSIS_HEADER = "บทวิเคราะห์"
UPGRADE_ACTIONS_HEADER = "3 สิ่งที่ควรทำ"


class FakeFetcher:
    """URL -> canned text; an Exception value is raised instead of returned."""

    def __init__(self) -> None:
        self.responses: dict[str, str | Exception] = {}
        self.calls: list[tuple[str, str]] = []  # (policy bucket, url)

    def set(self, url: str, response: str | Exception) -> None:
        self.responses[url] = response

    async def fetch(self, policy: FetchPolicy, url: str) -> str:
        self.calls.append((policy.name, url))
        response = self.responses.get(url)
        if response is None:
            raise ConnectionError(f"no fake response registered for {url}")
        if isinstance(response, Exception):
            raise response
        return response


class FakeChangeAnalyst:
    """classify returns the configured verdict (None -> rule-based fallback);
    upgrade_weekly_report appends the two executive sections like the real
    Anthropic analyst is prompted to."""

    def __init__(
        self,
        classification: ChangeClassification | None = None,
        *,
        upgrade: bool = True,
    ) -> None:
        self.classification = classification
        self.upgrade = upgrade
        self.classify_calls: list[tuple[str, str]] = []  # (diff, competitor_name)
        self.upgrade_calls: list[str] = []

    async def classify(self, diff: str, competitor_name: str) -> ChangeClassification | None:
        self.classify_calls.append((diff, competitor_name))
        return self.classification

    async def upgrade_weekly_report(self, draft: str) -> str:
        self.upgrade_calls.append(draft)
        if not self.upgrade:
            return draft
        return (
            f"{draft}\n\n{UPGRADE_ANALYSIS_HEADER}\n"
            "คู่แข่งกำลังขยับราคาช่วงไฮซีซั่น\n\n"
            f"{UPGRADE_ACTIONS_HEADER}\n1) เช็คราคา 2) อัปเดตเพจ 3) เตรียมโปรโมชั่น"
        )


class FakeRunRecorder:
    """RunRecorder with a settable 'spent today' figure for budget-guard tests."""

    def __init__(self, today_cost: Decimal = Decimal("0")) -> None:
        self.today_cost = today_cost
        self.rows: list[dict[str, Any]] = []

    async def cost_today_usd(self, now: datetime) -> Decimal:
        return self.today_cost

    async def record(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


# ------------------------------------------------------------ M4: agent runtime
# Fakes for the agent gateway ports (src/application/agents/ports.py), the
# AgentLlm seam, the Escalator and the budget CostAggregator. These import
# only stdlib + the pure agents modules, so they stay usable without the
# orchestrator package installed.

import random as _random  # noqa: E402

from src.application.agents.planning import PlannerInputs  # noqa: E402
from src.application.agents.ports import (  # noqa: E402
    ComposedReport,
    DeliveredReport,
    EvalCandidate,
    LlmCompletion,
    ReportRef,
    SeoInputs,
    SignalEvent,
)

FAKE_LLM_MODEL = "fake-model"


class FakeAgentLlm:
    """AgentLlm with scripted responses: each complete() pops the next entry.

    A None entry (or an exhausted script) means "LLM unavailable" — the agent
    must fall back to its deterministic path (additive-enhancement contract).
    """

    def __init__(self, *responses: str | None) -> None:
        self.responses: list[str | None] = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        tier: str,
        prompt: str,
        max_tokens: int,
        system: str | None = None,
    ) -> LlmCompletion | None:
        self.calls.append(
            {"tier": tier, "prompt": prompt, "max_tokens": max_tokens, "system": system}
        )
        text = self.responses.pop(0) if self.responses else None
        if text is None:
            return None
        return LlmCompletion(
            text=text,
            tokens_in=100,
            tokens_out=50,
            cost_usd=Decimal("0.0100"),
            model=FAKE_LLM_MODEL,
        )


class FakeEscalator:
    """Escalator recording (record, reason) pairs; never notifies anyone."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []

    async def escalate(self, record: Any, reason: str) -> None:
        self.calls.append((record, reason))


class FakeCostAggregator:
    """CostAggregator returning fixed per-agent sums (SqlDailyBudget tests)."""

    def __init__(self, sums: dict[str, Decimal] | None = None) -> None:
        self.sums = dict(sums or {})

    async def agent_costs_today(self, now: datetime) -> dict[str, Decimal]:
        return dict(self.sums)


class ScriptedRng(_random.Random):
    """random.Random whose random() pops scripted values (QA sampling tests)."""

    def __init__(self, values: list[float]) -> None:
        super().__init__(0)
        self.values = list(values)

    def random(self) -> float:  # type: ignore[override]
        return self.values.pop(0) if self.values else 1.0


def make_delivered(*, kind: str, period: str | None, body: str) -> DeliveredReport:
    return DeliveredReport(
        report_id=uuid.uuid4(),
        kind=kind,
        period=period,
        lang="th",
        body=body,
        line_sent=False,
        created_at=datetime.now(UTC),
    )


class FakeAnalyticsGateway:
    """AnalyticsGateway with canned drafts; records deliveries + upgrades."""

    UPGRADE_SUFFIX = f"\n\n{UPGRADE_ANALYSIS_HEADER}\nคู่แข่งขยับราคา"

    DAILY_DRAFT = "สรุปประจำวัน 4 ก.ค. 2569\n- ยอดเบิกรอจ่าย: 1 รายการ\n" "สิ่งสำคัญที่สุด: ไม่มีเรื่องเร่งด่วน"
    WEEKLY_DRAFT = "รายงานคู่แข่งประจำสัปดาห์ 22 มิ.ย. 2569 - 4 ก.ค. 2569\nยังไม่พบความเคลื่อนไหว"

    def __init__(
        self,
        daily_draft: str = DAILY_DRAFT,
        weekly_draft: str = WEEKLY_DRAFT,
    ) -> None:
        self.daily_draft = daily_draft
        self.weekly_draft = weekly_draft
        self.upgrade_calls: list[str] = []
        self.delivered: list[DeliveredReport] = []

    async def compose_daily(self) -> ComposedReport:
        return ComposedReport(body=self.daily_draft, period="2026-07-04")

    async def compose_weekly(self) -> ComposedReport:
        return ComposedReport(body=self.weekly_draft, period="2026-W26")

    async def upgrade_weekly(self, draft: str) -> str:
        self.upgrade_calls.append(draft)
        return draft + self.UPGRADE_SUFFIX

    async def deliver(self, *, kind: str, period: str, body: str) -> DeliveredReport:
        record = make_delivered(kind=kind, period=period, body=body)
        self.delivered.append(record)
        return record


class FakeMemoryGateway:
    """MemoryGateway over plain lists (consolidation + signal capture)."""

    def __init__(
        self,
        events: list[SignalEvent] | None = None,
        existing: list[tuple[str, str]] | None = None,
    ) -> None:
        self.events = list(events or [])
        self.existing = list(existing or [])  # (subject, body) already remembered
        self.remembered: list[tuple[str, str]] = []
        self.consolidate_calls = 0

    async def consolidate(self) -> tuple[int, int]:
        self.consolidate_calls += 1
        return (2, 1)

    async def recent_high_severity_events(self, hours: int) -> list[SignalEvent]:
        return list(self.events)

    async def find_similar(self, subject: str, body: str) -> list[tuple[str, str]]:
        return list(self.existing) + list(self.remembered)

    async def remember_signal(self, *, subject: str, body: str) -> None:
        self.remembered.append((subject, body))


class FakePlannerGateway:
    """PlannerGateway returning fixed inputs; records deliveries."""

    def __init__(self, inputs: PlannerInputs | None = None) -> None:
        self.inputs = inputs or PlannerInputs()
        self.delivered: list[DeliveredReport] = []

    async def gather_inputs(self) -> PlannerInputs:
        return self.inputs

    async def deliver(self, *, period: str, body: str) -> DeliveredReport:
        record = make_delivered(kind="planning", period=period, body=body)
        self.delivered.append(record)
        return record


class FakeQaGateway:
    """QaGateway over a fixed candidate list; records written evals."""

    def __init__(self, candidates: list[EvalCandidate] | None = None) -> None:
        self.candidates = list(candidates or [])
        self.evals: list[dict[str, Any]] = []

    async def eval_candidates(self, days: int) -> list[EvalCandidate]:
        return list(self.candidates)

    async def write_eval(self, *, run_id: uuid.UUID, rubric: str, score: int, notes: str) -> None:
        self.evals.append({"run_id": run_id, "rubric": rubric, "score": score, "notes": notes})


class FakeMarketingGateway:
    """MarketingGateway (M6) over plain lists: SEO inputs, upstream reports by
    kind, and recorded deliveries."""

    def __init__(
        self,
        *,
        seo_inputs: SeoInputs | None = None,
        reports: dict[str, list[ReportRef]] | None = None,
    ) -> None:
        self.seo_inputs = seo_inputs or SeoInputs()
        self.reports = {kind: list(refs) for kind, refs in (reports or {}).items()}
        self.delivered: list[DeliveredReport] = []

    async def gather_seo_inputs(self) -> SeoInputs:
        return self.seo_inputs

    async def recent_reports(self, kind: str, limit: int) -> list[ReportRef]:
        return list(self.reports.get(kind, []))[:limit]

    async def deliver(
        self, *, kind: str, period: str, body: str, lang: str, line: bool
    ) -> DeliveredReport:
        record = DeliveredReport(
            report_id=uuid.uuid4(),
            kind=kind,
            period=period,
            lang=lang,
            body=body,
            line_sent=line,
            created_at=datetime.now(UTC),
        )
        self.delivered.append(record)
        return record


def make_report_ref(body: str, *, period: str | None = None) -> ReportRef:
    return ReportRef(
        report_id=uuid.uuid4(),
        period=period,
        body=body,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------- M5: lead discovery
# Fakes for the LeadCollector port and the LeadSource/LeadDiscovery/
# LeadMaintenance repository protocols (pipeline + registry + maintenance
# unit tests, and the create_app/AgentRuntime integration seam).

from src.application.errors import CollectorNotConfiguredError  # noqa: E402
from src.application.lead_discovery import CollectedDoc  # noqa: E402


@dataclass
class FakeLeadSourceRow:
    id: uuid.UUID
    name: str
    type: str
    url: str | None = None
    config_json: dict[str, Any] | None = None
    tos_policy: str = "allowed"
    rate_limit_per_hr: int = 12
    enabled: bool = True
    competitor_id: uuid.UUID | None = None
    last_checked_at: datetime | None = None
    last_status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeLeadRow:
    id: uuid.UUID
    kind: str
    name: str
    dedup_hash: str
    source_id: uuid.UUID | None = None
    contact_json: dict[str, Any] | None = None
    locale: str | None = None
    intent_score: int = 0
    stage: str = "discovered"
    cluster_id: uuid.UUID | None = None
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None


@dataclass
class FakeLeadEventRow:
    lead_id: uuid.UUID
    type: str
    payload_json: dict[str, Any] | None
    occurred_at: datetime


@dataclass
class FakeLeadScoreRow:
    lead_id: uuid.UUID
    model_version: str
    score: int
    features_json: dict[str, Any] | None
    scored_at: datetime


@dataclass
class FakeRawLeadDocumentRow:
    id: uuid.UUID
    source_id: uuid.UUID
    content_hash: str
    storage_key: str
    status: str


class FakeLeadCollector:
    """LeadCollector returning canned docs per source id.

    An Exception value raises instead of returning; `not_configured` raises
    CollectorNotConfiguredError (the 'skipped: no credentials' path)."""

    def __init__(self) -> None:
        self.docs: dict[uuid.UUID, list[CollectedDoc] | Exception] = {}
        self.not_configured: set[uuid.UUID] = set()
        self.calls: list[uuid.UUID] = []

    def set(self, source_id: uuid.UUID, docs: list[CollectedDoc] | Exception) -> None:
        self.docs[source_id] = docs

    async def collect(self, source: Any) -> list[CollectedDoc]:
        self.calls.append(source.id)
        if source.id in self.not_configured:
            raise CollectorNotConfiguredError(source.type)
        response = self.docs.get(source.id)
        if response is None:
            return []
        if isinstance(response, Exception):
            raise response
        return list(response)


class FakeLeadStore:
    """Dict-backed store satisfying the LeadSourceRepository,
    LeadDiscoveryRepository and LeadMaintenanceRepository protocols."""

    def __init__(self) -> None:
        self.sources: dict[uuid.UUID, FakeLeadSourceRow] = {}
        self.raw_documents: dict[uuid.UUID, FakeRawLeadDocumentRow] = {}
        self.leads: dict[uuid.UUID, FakeLeadRow] = {}
        self.lead_events: list[FakeLeadEventRow] = []
        self.lead_scores: list[FakeLeadScoreRow] = []

    # ----------------------------------------------------------- registry

    def add_source(
        self,
        name: str,
        type: str,  # noqa: A002 - mirrors the protocol
        *,
        url: str | None = None,
        config: dict[str, Any] | None = None,
        enabled: bool = True,
        competitor_id: uuid.UUID | None = None,
    ) -> FakeLeadSourceRow:
        row = FakeLeadSourceRow(
            id=uuid.uuid4(),
            name=name,
            type=type,
            url=url,
            config_json=config,
            enabled=enabled,
            competitor_id=competitor_id,
        )
        self.sources[row.id] = row
        return row

    async def list_lead_sources(self) -> list[FakeLeadSourceRow]:
        return [row for row in self.sources.values() if row.competitor_id is None]

    async def get_source(self, source_id: uuid.UUID) -> FakeLeadSourceRow | None:
        return self.sources.get(source_id)

    async def create_lead_source(
        self,
        *,
        name: str,
        type: str,  # noqa: A002 - mirrors the protocol
        url: str | None,
        config: dict[str, Any] | None,
        rate_limit_per_hr: int,
    ) -> FakeLeadSourceRow:
        row = FakeLeadSourceRow(
            id=uuid.uuid4(),
            name=name,
            type=type,
            url=url,
            config_json=config,
            rate_limit_per_hr=rate_limit_per_hr,
        )
        self.sources[row.id] = row
        return row

    async def update_source(
        self, source_id: uuid.UUID, changes: dict[str, Any]
    ) -> FakeLeadSourceRow:
        row = self.sources[source_id]
        for key, value in changes.items():
            setattr(row, key, value)
        return row

    async def delete_source(self, source_id: uuid.UUID) -> None:
        self.sources.pop(source_id, None)

    # ----------------------------------------------------------- pipeline

    async def enabled_lead_sources(self) -> list[FakeLeadSourceRow]:
        return [row for row in self.sources.values() if row.competitor_id is None and row.enabled]

    async def set_source_result(
        self, source_id: uuid.UUID, status: str, checked_at: datetime | None
    ) -> None:
        source = self.sources.get(source_id)
        if source is None:
            return
        source.last_status = status
        if checked_at is not None:
            source.last_checked_at = checked_at

    async def raw_document_exists(self, source_id: uuid.UUID, content_hash: str) -> bool:
        return any(
            raw.source_id == source_id and raw.content_hash == content_hash
            for raw in self.raw_documents.values()
        )

    async def create_raw_document(
        self, *, source_id: uuid.UUID, content_hash: str, storage_key: str, status: str
    ) -> FakeRawLeadDocumentRow:
        row = FakeRawLeadDocumentRow(
            id=uuid.uuid4(),
            source_id=source_id,
            content_hash=content_hash,
            storage_key=storage_key,
            status=status,
        )
        self.raw_documents[row.id] = row
        return row

    async def set_raw_document_status(self, raw_id: uuid.UUID, status: str) -> None:
        raw = self.raw_documents.get(raw_id)
        if raw is not None:
            raw.status = status

    async def find_lead_by_dedup(self, dedup_hash: str) -> FakeLeadRow | None:
        for lead in self.leads.values():
            if lead.dedup_hash == dedup_hash and lead.deleted_at is None:
                return lead
        return None

    async def get_lead(self, lead_id: uuid.UUID) -> FakeLeadRow | None:
        lead = self.leads.get(lead_id)
        return lead if lead is not None and lead.deleted_at is None else None

    async def create_lead(
        self,
        *,
        source_id: uuid.UUID,
        kind: str,
        name: str,
        contact_json: dict[str, Any] | None,
        locale: str | None,
        intent_score: int,
        dedup_hash: str,
        first_seen_at: datetime,
    ) -> FakeLeadRow:
        row = FakeLeadRow(
            id=uuid.uuid4(),
            source_id=source_id,
            kind=kind,
            name=name,
            contact_json=contact_json,
            locale=locale,
            intent_score=intent_score,
            dedup_hash=dedup_hash,
            first_seen_at=first_seen_at,
            last_activity_at=first_seen_at,
        )
        self.leads[row.id] = row
        return row

    async def touch_lead(self, lead_id: uuid.UUID, activity_at: datetime) -> None:
        lead = self.leads.get(lead_id)
        if lead is not None:
            lead.last_activity_at = activity_at

    async def add_lead_event(
        self,
        lead_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any] | None,
        occurred_at: datetime,
    ) -> None:
        self.lead_events.append(
            FakeLeadEventRow(
                lead_id=lead_id,
                type=event_type,
                payload_json=payload,
                occurred_at=occurred_at,
            )
        )

    async def add_lead_score(
        self,
        lead_id: uuid.UUID,
        *,
        model_version: str,
        score: int,
        features: dict[str, Any] | None,
        scored_at: datetime,
    ) -> None:
        self.lead_scores.append(
            FakeLeadScoreRow(
                lead_id=lead_id,
                model_version=model_version,
                score=score,
                features_json=features,
                scored_at=scored_at,
            )
        )

    # -------------------------------------------------------- maintenance

    async def leads_for_clustering(self) -> list[tuple[uuid.UUID, str]]:
        rows: list[tuple[uuid.UUID, str]] = []
        for lead in self.leads.values():
            if lead.deleted_at is not None:
                continue
            excerpt = ""
            for event in reversed(self.lead_events):  # newest first
                if event.lead_id == lead.id and event.type == "discovered":
                    payload = event.payload_json or {}
                    value = payload.get("excerpt")
                    if isinstance(value, str):
                        excerpt = value
                    break
            rows.append((lead.id, f"{lead.name} {excerpt}".strip()))
        return rows

    async def set_cluster_ids(self, mapping: dict[uuid.UUID, uuid.UUID]) -> None:
        for lead_id, cluster_id in mapping.items():
            if lead_id in self.leads:
                self.leads[lead_id].cluster_id = cluster_id

    async def stale_leads(self, cutoff: datetime, *, exclude_name: str) -> list[FakeLeadRow]:
        rows = []
        for lead in self.leads.values():
            if lead.deleted_at is not None or lead.stage == "won":
                continue
            activity = lead.last_activity_at or lead.first_seen_at
            if activity >= cutoff:
                continue
            if lead.contact_json is None and lead.name == exclude_name:
                continue  # already anonymized
            rows.append(lead)
        return rows

    async def anonymize_lead(self, lead_id: uuid.UUID, name: str) -> None:
        lead = self.leads[lead_id]
        lead.name = name
        lead.contact_json = None

    # -------------------------------------------------------------- assertions

    def events_for(self, lead_id: uuid.UUID, event_type: str) -> list[FakeLeadEventRow]:
        return [
            event
            for event in self.lead_events
            if event.lead_id == lead_id and event.type == event_type
        ]


@dataclass
class FakeCompetitorRow:
    id: uuid.UUID
    name: str
    kind: str | None = None
    website: str | None = None
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeSourceRow:
    id: uuid.UUID
    name: str
    type: str
    url: str | None
    tos_policy: str = "allowed"
    rate_limit_per_hr: int = 6
    enabled: bool = True
    competitor_id: uuid.UUID | None = None
    competitor_name: str | None = None
    last_checked_at: datetime | None = None
    last_status: str | None = None


@dataclass
class FakeSnapshotRow:
    id: uuid.UUID
    competitor_id: uuid.UUID
    source_id: uuid.UUID | None
    captured_at: datetime
    content_hash: str
    storage_key: str


@dataclass
class FakeChangeEventRow:
    id: uuid.UUID
    competitor_id: uuid.UUID
    competitor_name: str
    snapshot_id: uuid.UUID | None
    category: str
    summary: str
    severity: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeReportRow:
    id: uuid.UUID
    kind: str
    period: str | None
    lang: str
    body: str | None
    sent_at: datetime | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeCompetitorIntelRepository:
    """Dict-backed CompetitorIntelRepository for sweep/report unit tests."""

    def __init__(self) -> None:
        self.competitors: dict[uuid.UUID, FakeCompetitorRow] = {}
        self.sources: dict[uuid.UUID, FakeSourceRow] = {}
        self.snapshots: list[FakeSnapshotRow] = []
        self.change_events: list[FakeChangeEventRow] = []
        self.reports: list[FakeReportRow] = []
        self._tick = 0

    def _now(self) -> datetime:
        # Strictly increasing timestamps so latest_snapshot ordering is stable
        # even when several rows land within the same wall-clock microsecond.
        self._tick += 1
        return datetime.now(UTC) + timedelta(microseconds=self._tick)

    def add_competitor(
        self, name: str, *, active: bool = True, website: str | None = None
    ) -> FakeCompetitorRow:
        row = FakeCompetitorRow(id=uuid.uuid4(), name=name, active=active, website=website)
        self.competitors[row.id] = row
        return row

    async def get_competitor(self, competitor_id: uuid.UUID) -> FakeCompetitorRow | None:
        return self.competitors.get(competitor_id)

    async def create_competitor(
        self,
        *,
        name: str,
        kind: str | None,
        website: str | None,
        listing_urls: dict[str, Any] | None,
    ) -> FakeCompetitorRow:
        row = FakeCompetitorRow(id=uuid.uuid4(), name=name, kind=kind, website=website)
        self.competitors[row.id] = row
        return row

    async def create_source(
        self,
        *,
        name: str,
        type: str,  # noqa: A002 - mirrors the protocol
        url: str,
        competitor_id: uuid.UUID | None,
        rate_limit_per_hr: int,
        tos_policy: str,
        robots_ok: bool,
        enabled: bool,
    ) -> FakeSourceRow:
        competitor = self.competitors.get(competitor_id) if competitor_id else None
        row = FakeSourceRow(
            id=uuid.uuid4(),
            name=name,
            type=type,
            url=url,
            tos_policy=tos_policy,
            rate_limit_per_hr=rate_limit_per_hr,
            enabled=enabled,
            competitor_id=competitor_id,
            competitor_name=competitor.name if competitor else None,
        )
        self.sources[row.id] = row
        return row

    async def get_source(self, source_id: uuid.UUID) -> FakeSourceRow | None:
        return self.sources.get(source_id)

    async def delete_source(self, source_id: uuid.UUID) -> None:
        self.sources.pop(source_id, None)

    async def list_sources(self, competitor_id: uuid.UUID | None) -> list[FakeSourceRow]:
        return [
            row
            for row in self.sources.values()
            if competitor_id is None or row.competitor_id == competitor_id
        ]

    async def sweep_sources(self, competitor_id: uuid.UUID | None) -> list[FakeSourceRow]:
        rows = []
        for row in self.sources.values():
            if not row.enabled or row.competitor_id is None:
                continue
            competitor = self.competitors.get(row.competitor_id)
            if competitor is None or not competitor.active:
                continue
            if competitor_id is not None and row.competitor_id != competitor_id:
                continue
            rows.append(row)
        return rows

    async def set_source_result(
        self, source_id: uuid.UUID, status: str, checked_at: datetime | None
    ) -> None:
        source = self.sources.get(source_id)
        if source is None:
            return
        source.last_status = status
        if checked_at is not None:
            source.last_checked_at = checked_at

    async def latest_snapshot(
        self, competitor_id: uuid.UUID, source_id: uuid.UUID
    ) -> FakeSnapshotRow | None:
        rows = [
            row
            for row in self.snapshots
            if row.competitor_id == competitor_id and row.source_id == source_id
        ]
        return max(rows, key=lambda row: row.captured_at) if rows else None

    async def create_snapshot(
        self,
        *,
        competitor_id: uuid.UUID,
        source_id: uuid.UUID,
        content_hash: str,
        storage_key: str,
    ) -> FakeSnapshotRow:
        row = FakeSnapshotRow(
            id=uuid.uuid4(),
            competitor_id=competitor_id,
            source_id=source_id,
            captured_at=self._now(),
            content_hash=content_hash,
            storage_key=storage_key,
        )
        self.snapshots.append(row)
        return row

    async def create_change_event(
        self,
        *,
        competitor_id: uuid.UUID,
        snapshot_id: uuid.UUID | None,
        category: str,
        summary: str,
        severity: str,
    ) -> FakeChangeEventRow:
        competitor = self.competitors.get(competitor_id)
        row = FakeChangeEventRow(
            id=uuid.uuid4(),
            competitor_id=competitor_id,
            competitor_name=competitor.name if competitor else "",
            snapshot_id=snapshot_id,
            category=category,
            summary=summary,
            severity=severity,
            detected_at=self._now(),
        )
        self.change_events.append(row)
        return row

    async def change_events_since(self, since: datetime) -> list[FakeChangeEventRow]:
        return [row for row in self.change_events if row.detected_at >= since]

    async def create_report(
        self, *, kind: str, period: str, lang: str, body: str, sent_at: datetime | None
    ) -> FakeReportRow:
        row = FakeReportRow(
            id=uuid.uuid4(), kind=kind, period=period, lang=lang, body=body, sent_at=sent_at
        )
        self.reports.append(row)
        return row
