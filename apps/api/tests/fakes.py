"""In-memory fakes for the M2 gateway ports (src/application/ports.py).

Shared by the unit tests and the DATABASE_URL-gated integration tests: the
integration suite runs with ONLY PostgreSQL available — MinIO, Meilisearch
and Qdrant are replaced by these fakes via create_app(kb_adapters=...). The
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

    async def search(
        self, collection: str, vector: Sequence[float], limit: int
    ) -> list[VectorHit]:
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

    async def search(
        self, collection: str, vector: Sequence[float], limit: int
    ) -> list[VectorHit]:
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
        rows = [
            row
            for row in self.documents.values()
            if status is None or row.status == status
        ]
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
        return row.consolidated_into is None and (
            row.expires_at is None or row.expires_at > now
        )

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
