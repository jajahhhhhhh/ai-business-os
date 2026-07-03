"""Knowledge-base use cases (M2): document ingestion, processing, hybrid search.

Graceful degradation (NFR-1): the keyword side (Meilisearch) is mandatory for
an indexed document; the semantic side (bge-m3 + Qdrant) is best-effort. When
the embedder or Qdrant is unavailable, ingestion still indexes keywords
(documents.embedded stays false — the flag reflects reality) and hybrid
search degrades to keyword-only with ``degraded=True`` on the response.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from src.application.errors import EmptyDocumentError, NotFoundError
from src.application.ports import (
    Embedder,
    KeywordChunk,
    KeywordIndex,
    ObjectStorage,
    TextExtractor,
    VectorIndex,
    VectorPoint,
)
from src.application.repositories import AuditWriter, DocumentRow, KnowledgeBaseRepository
from src.domain.chunking import chunk_text
from src.domain.fusion import rrf_fuse

KB_COLLECTION = "kb_chunks"
MAX_SEARCH_LIMIT = 50
SNIPPET_CHARS = 400
ERROR_MAX_CHARS = 500

SearchMode = Literal["hybrid", "keyword", "semantic"]


@dataclass(frozen=True, slots=True)
class DocumentDetail:
    document: DocumentRow
    chunk_count: int


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    seq: int
    text: str
    score: float
    matched_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchResults:
    query: str
    mode: str
    degraded: bool
    results: list[SearchResultItem]


class KnowledgeBaseUseCases:
    def __init__(
        self,
        repo: KnowledgeBaseRepository,
        audit: AuditWriter,
        *,
        storage: ObjectStorage,
        keyword_index: KeywordIndex,
        vector_index: VectorIndex,
        embedder: Embedder,
        extract: TextExtractor,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._storage = storage
        self._keyword = keyword_index
        self._vector = vector_index
        self._embedder = embedder
        self._extract = extract

    # ------------------------------------------------------------- ingestion

    async def ingest_document(
        self,
        *,
        data: bytes,
        filename: str,
        mime: str,
        title: str | None,
        lang: str | None,
        source: str,
        actor: str,
    ) -> DocumentRow:
        """Store the original bytes and create a pending documents row.

        Parsing/indexing happens later in process_document (worker task).
        """
        document_id = uuid.uuid4()
        safe_name = filename.replace("/", "_").strip() or "document"
        storage_key = f"kb/{document_id}/{safe_name}"
        await self._storage.put(storage_key, data, mime)
        row = await self._repo.create_document(
            id=document_id,
            title=(title or "").strip() or safe_name,
            mime=mime,
            storage_key=storage_key,
            lang=lang,
            size_bytes=len(data),
            source=source,
        )
        await self._audit.write(
            actor,
            "kb.document_uploaded",
            "documents",
            document_id,
            {"title": row.title, "mime": mime, "size_bytes": len(data), "source": source},
        )
        return row

    async def process_document(
        self, document_id: uuid.UUID, actor: str = "worker"
    ) -> DocumentRow:
        """Parse -> chunk -> index one document. Raises on failure.

        The caller (src/worker.py run_document_pipeline) persists
        status='failed' in a FRESH session on error, because a failed pipeline
        may leave the current transaction unusable. Everything here runs in
        one transaction, so the intermediate 'parsing' status only becomes
        externally visible if the caller commits it — acceptable for M2.
        """
        doc = await self._repo.get_document(document_id)
        if doc is None:
            raise NotFoundError("document", document_id)
        await self._repo.update_document(document_id, {"status": "parsing", "error": None})

        data = await self._storage.get(doc.storage_key)
        # Extraction is sync and possibly OCR-slow; keep the event loop free.
        parsed = await asyncio.to_thread(self._extract, data, doc.mime)
        chunks = chunk_text(parsed.text)
        if not chunks:
            raise EmptyDocumentError()

        rows = list(
            await self._repo.replace_chunks(document_id, [(c.seq, c.text) for c in chunks])
        )
        # New chunk rows get new uuids, so drop the old index entries first.
        await self._keyword.delete_document(document_id)
        await self._keyword.index_chunks(
            [
                KeywordChunk(
                    id=row.id,
                    document_id=document_id,
                    document_title=doc.title,
                    lang=doc.lang,
                    seq=row.seq,
                    text=row.text,
                )
                for row in rows
            ]
        )

        embedded = False
        if self._embedder.is_available:
            try:
                vectors = await self._embedder.embed_texts([row.text for row in rows])
                await self._vector.delete_document(KB_COLLECTION, document_id)
                await self._vector.upsert(
                    KB_COLLECTION,
                    [
                        VectorPoint(
                            id=str(row.id),
                            vector=vector,
                            payload={
                                "chunk_id": str(row.id),
                                "document_id": str(document_id),
                                "seq": row.seq,
                            },
                        )
                        for row, vector in zip(rows, vectors, strict=True)
                    ],
                )
                await self._repo.set_chunk_point_ids([row.id for row in rows])
                embedded = True
            except Exception:  # noqa: BLE001 - NFR-1: Qdrant down must not fail the doc
                embedded = False

        updated = await self._repo.update_document(
            document_id,
            {
                "status": "indexed",
                "error": None,
                "ocr_done": parsed.ocr_used,
                "meili_indexed": True,
                "embedded": embedded,
            },
        )
        await self._audit.write(
            actor,
            "kb.document_indexed",
            "documents",
            document_id,
            {"chunks": len(rows), "embedded": embedded, "ocr_used": parsed.ocr_used},
        )
        return updated

    # ------------------------------------------------------------- queries

    async def list_documents(self, status: str | None, limit: int) -> list[DocumentRow]:
        return list(await self._repo.list_documents(status, max(1, min(limit, 200))))

    async def get_document(self, document_id: uuid.UUID) -> DocumentDetail:
        doc = await self._repo.get_document(document_id)
        if doc is None:
            raise NotFoundError("document", document_id)
        return DocumentDetail(document=doc, chunk_count=await self._repo.chunk_count(document_id))

    async def search(
        self, q: str, mode: SearchMode = "hybrid", limit: int = 10
    ) -> SearchResults:
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        keyword_ids: list[str] = []
        semantic_ids: list[str] = []
        degraded = False

        if mode == "keyword":
            keyword_ids = await self._keyword.search(q, limit)
        elif mode == "semantic":
            semantic_ids, degraded = await self._semantic_ids(q, limit)
        else:
            keyword_ids, (semantic_ids, degraded) = await asyncio.gather(
                self._keyword.search(q, limit), self._semantic_ids(q, limit)
            )

        fused = rrf_fuse([keyword_ids, semantic_ids])[:limit]
        rows = await self._repo.get_chunks_with_titles([uuid.UUID(cid) for cid, _ in fused])
        by_id = {str(row.id): row for row in rows}
        keyword_set, semantic_set = set(keyword_ids), set(semantic_ids)

        results: list[SearchResultItem] = []
        for chunk_id, score in fused:
            row = by_id.get(chunk_id)
            if row is None:  # index entry with no Postgres row (mid-reindex); skip
                continue
            matched_by = tuple(
                side
                for side, members in (("keyword", keyword_set), ("semantic", semantic_set))
                if chunk_id in members
            )
            results.append(
                SearchResultItem(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    document_title=row.document_title,
                    seq=row.seq,
                    text=row.text[:SNIPPET_CHARS],
                    score=score,
                    matched_by=matched_by,
                )
            )
        return SearchResults(query=q, mode=mode, degraded=degraded, results=results)

    async def _semantic_ids(self, q: str, limit: int) -> tuple[list[str], bool]:
        """Ranked chunk ids from the vector side, plus a degraded flag."""
        if not self._embedder.is_available:
            return [], True
        try:
            vector = await self._embedder.embed_query(q)
            hits = await self._vector.search(KB_COLLECTION, vector, limit)
        except Exception:  # noqa: BLE001 - NFR-1: semantic side degrades, never breaks search
            return [], True
        return [str(hit.payload.get("chunk_id", hit.id)) for hit in hits], False
