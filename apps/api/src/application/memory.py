"""Agent memory use cases (M2): remember, recall, weekly consolidation.

Recall always includes a Postgres ILIKE ranking so memory works with zero
optional services; when the embedder + Qdrant are up, a semantic ranking is
RRF-fused with it. Consolidation merges near-duplicates (embedding cosine
similarity >= 0.92 within the same kind; exact (kind, subject) match when
vectors are unavailable) and hard-deletes expired rows.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.ports import Embedder, VectorIndex, VectorPoint
from src.application.repositories import AuditWriter, MemoryRepository, MemoryRow
from src.domain.errors import InvalidImportanceError
from src.domain.fusion import rrf_fuse

MEMORY_COLLECTION = "memories"
SIMILARITY_THRESHOLD = 0.92
MAX_RECALL_LIMIT = 50


@dataclass(frozen=True, slots=True)
class RecallHit:
    memory: MemoryRow
    score: float


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    merged: int
    expired: int


def _embedding_text(subject: str, body: str) -> str:
    return f"{subject}\n{body}"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _union_groups(count: int, pairs: list[tuple[int, int]]) -> list[list[int]]:
    """Union-find over index pairs; returns index groups in stable order."""
    parent = list(range(count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[int]] = {}
    for i in range(count):
        groups.setdefault(find(i), []).append(i)
    return [groups[root] for root in sorted(groups)]


class MemoryUseCases:
    def __init__(
        self,
        repo: MemoryRepository,
        audit: AuditWriter,
        *,
        vector_index: VectorIndex,
        embedder: Embedder,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._vector = vector_index
        self._embedder = embedder

    async def remember(
        self,
        *,
        kind: str,
        subject: str,
        body: str,
        importance: int = 3,
        expires_at: datetime | None = None,
        actor: str,
        source_run_id: uuid.UUID | None = None,
    ) -> MemoryRow:
        if not 1 <= importance <= 5:
            raise InvalidImportanceError(f"importance must be 1-5, got {importance}")
        row = await self._repo.create(
            kind=kind,
            subject=subject,
            body=body,
            importance=importance,
            expires_at=expires_at,
            source_run_id=source_run_id,
        )
        if self._embedder.is_available:
            try:
                vector = await self._embedder.embed_query(_embedding_text(subject, body))
                await self._vector.upsert(
                    MEMORY_COLLECTION,
                    [
                        VectorPoint(
                            id=str(row.id),
                            vector=vector,
                            payload={"memory_id": str(row.id), "kind": kind},
                        )
                    ],
                )
                row = await self._repo.set_embedding_point(row.id, str(row.id))
            except Exception:  # noqa: BLE001 - NFR-1: memory works without the vector side
                pass
        await self._audit.write(
            actor,
            "memory.remembered",
            "memories",
            row.id,
            {"kind": kind, "subject": subject, "importance": importance},
        )
        return row

    async def recall(self, q: str, kind: str | None = None, limit: int = 8) -> list[RecallHit]:
        limit = max(1, min(limit, MAX_RECALL_LIMIT))
        now = datetime.now(UTC)

        # ALWAYS ranked: Postgres ILIKE over subject/body (excludes expired
        # and consolidated rows at the query level).
        text_rows = list(await self._repo.search_text(q, kind, limit, now))
        text_ids = [str(row.id) for row in text_rows]

        semantic_ids: list[str] = []
        if self._embedder.is_available:
            try:
                vector = await self._embedder.embed_query(q)
                hits = await self._vector.search(MEMORY_COLLECTION, vector, limit)
                semantic_ids = [str(hit.payload.get("memory_id", hit.id)) for hit in hits]
            except Exception:  # noqa: BLE001 - NFR-1: fall back to the ILIKE ranking alone
                semantic_ids = []

        fused = rrf_fuse([text_ids, semantic_ids])
        # Hydration re-checks expiry/consolidation: the vector index may still
        # hold points for rows that expired or were merged since indexing.
        rows = await self._repo.get_active_many([uuid.UUID(mid) for mid, _ in fused], now)
        by_id = {str(row.id): row for row in rows}
        results: list[RecallHit] = []
        for memory_id, score in fused:
            row = by_id.get(memory_id)
            if row is None or (kind is not None and row.kind != kind):
                continue
            results.append(RecallHit(memory=row, score=score))
            if len(results) >= limit:
                break
        return results

    async def consolidate(self, actor: str) -> ConsolidationResult:
        now = datetime.now(UTC)

        # 1. Hard-delete expired memories (and their vector points).
        expired_rows = list(await self._repo.list_expired(now))
        if expired_rows:
            await self._delete_points(
                [row.embedding_point_id for row in expired_rows if row.embedding_point_id]
            )
            await self._repo.delete_many([row.id for row in expired_rows])

        # 2. Merge near-duplicates among the survivors.
        active = list(await self._repo.list_active(now))
        merged = 0
        for group in await self._group_duplicates(active):
            if len(group) < 2:
                continue
            # Keep the highest-importance memory; newest wins a tie.
            survivor = max(group, key=lambda row: (row.importance, row.created_at))
            losers = [row for row in group if row.id != survivor.id]
            await self._repo.mark_consolidated([row.id for row in losers], survivor.id)
            await self._delete_points(
                [row.embedding_point_id for row in losers if row.embedding_point_id]
            )
            merged += len(losers)

        await self._audit.write(
            actor,
            "memory.consolidated",
            "memories",
            None,
            {"merged": merged, "expired": len(expired_rows)},
        )
        return ConsolidationResult(merged=merged, expired=len(expired_rows))

    async def _group_duplicates(self, rows: list[MemoryRow]) -> list[list[MemoryRow]]:
        """Duplicate groups: embedding similarity when available, else exact
        (kind, subject) match. Merging never crosses kinds."""
        if not rows:
            return []
        if self._embedder.is_available:
            try:
                vectors = await self._embedder.embed_texts(
                    [_embedding_text(row.subject, row.body) for row in rows]
                )
            except Exception:  # noqa: BLE001 - NFR-1: degrade to exact-subject grouping
                vectors = None
            if vectors is not None:
                pairs = [
                    (i, j)
                    for i in range(len(rows))
                    for j in range(i + 1, len(rows))
                    if rows[i].kind == rows[j].kind
                    and _cosine(vectors[i], vectors[j]) >= SIMILARITY_THRESHOLD
                ]
                return [[rows[i] for i in group] for group in _union_groups(len(rows), pairs)]
        by_key: dict[tuple[str, str], list[MemoryRow]] = {}
        for row in rows:
            by_key.setdefault((row.kind, row.subject), []).append(row)
        return list(by_key.values())

    async def _delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        try:
            await self._vector.delete_points(MEMORY_COLLECTION, point_ids)
        except Exception:  # noqa: BLE001 - NFR-1: Qdrant down must not block consolidation
            pass
