"""KB use cases against in-memory fakes: pipeline flags + hybrid search fusion."""

from __future__ import annotations

import pytest

from src.application.errors import EmptyDocumentError, UnsupportedDocumentError
from src.application.kb import KB_COLLECTION, SNIPPET_CHARS, KnowledgeBaseUseCases
from src.application.ports import ParseResult
from tests.fakes import (
    BrokenVectorIndex,
    FakeEmbedder,
    FakeKnowledgeBaseRepository,
    InMemoryKeywordIndex,
    InMemoryObjectStorage,
    InMemoryVectorIndex,
    NullAuditWriter,
    fake_extract,
)

THAI_TEXT = "ใบเสนอราคางานไฟฟ้า วิลล่าลิปะน้อย จำนวน 450,000 บาท"


def make_use_cases(
    *,
    embedder: FakeEmbedder | None = None,
    vector_index=None,
    extract=fake_extract,
) -> tuple[KnowledgeBaseUseCases, FakeKnowledgeBaseRepository, InMemoryKeywordIndex, object]:
    repo = FakeKnowledgeBaseRepository()
    keyword = InMemoryKeywordIndex()
    vector = vector_index if vector_index is not None else InMemoryVectorIndex()
    use_cases = KnowledgeBaseUseCases(
        repo,
        NullAuditWriter(),
        storage=InMemoryObjectStorage(),
        keyword_index=keyword,
        vector_index=vector,
        embedder=embedder if embedder is not None else FakeEmbedder(available=True),
        extract=extract,
    )
    return use_cases, repo, keyword, vector


async def ingest_and_process(use_cases: KnowledgeBaseUseCases, text: str, title: str):
    document = await use_cases.ingest_document(
        data=text.encode("utf-8"),
        filename=f"{title}.txt",
        mime="text/plain",
        title=title,
        lang="th",
        source="upload",
        actor="test",
    )
    return await use_cases.process_document(document.id)


class TestPipeline:
    async def test_ingest_creates_pending_document(self) -> None:
        use_cases, repo, _, _ = make_use_cases()
        document = await use_cases.ingest_document(
            data=b"hello",
            filename="a.txt",
            mime="text/plain",
            title=None,
            lang=None,
            source="upload",
            actor="test",
        )
        assert document.status == "pending"
        assert document.title == "a.txt"  # falls back to the filename
        assert document.size_bytes == 5
        assert document.storage_key == f"kb/{document.id}/a.txt"

    async def test_process_indexes_keyword_and_vector(self) -> None:
        use_cases, repo, keyword, vector = make_use_cases()
        document = await ingest_and_process(use_cases, THAI_TEXT, "quote")
        assert document.status == "indexed"
        assert document.meili_indexed is True
        assert document.embedded is True
        assert document.error is None
        assert await repo.chunk_count(document.id) == 1
        assert len(keyword.chunks) == 1
        assert len(vector.collections[KB_COLLECTION]) == 1
        (chunk,) = repo.chunks.values()
        assert chunk.qdrant_point_id == str(chunk.id)

    async def test_embedder_unavailable_still_indexes_keyword(self) -> None:
        use_cases, repo, keyword, vector = make_use_cases(
            embedder=FakeEmbedder(available=False)
        )
        document = await ingest_and_process(use_cases, THAI_TEXT, "quote")
        assert document.status == "indexed"
        assert document.meili_indexed is True
        assert document.embedded is False  # the flag reflects reality (NFR-1)
        assert len(keyword.chunks) == 1

    async def test_qdrant_down_degrades_to_keyword_only(self) -> None:
        use_cases, _, keyword, _ = make_use_cases(vector_index=BrokenVectorIndex())
        document = await ingest_and_process(use_cases, THAI_TEXT, "quote")
        assert document.status == "indexed"
        assert document.embedded is False
        assert len(keyword.chunks) == 1

    async def test_reprocess_replaces_chunks(self) -> None:
        use_cases, repo, keyword, _ = make_use_cases()
        document = await ingest_and_process(use_cases, THAI_TEXT, "quote")
        again = await use_cases.process_document(document.id)
        assert again.status == "indexed"
        assert await repo.chunk_count(document.id) == 1
        assert len(keyword.chunks) == 1  # old entries were deleted first

    async def test_unsupported_mime_raises(self) -> None:
        def raising_extract(data: bytes, mime: str) -> ParseResult:
            raise UnsupportedDocumentError(mime)

        use_cases, _, _, _ = make_use_cases(extract=raising_extract)
        document = await use_cases.ingest_document(
            data=b"zip",
            filename="a.zip",
            mime="application/zip",
            title=None,
            lang=None,
            source="upload",
            actor="test",
        )
        with pytest.raises(UnsupportedDocumentError):
            await use_cases.process_document(document.id)

    async def test_empty_text_raises(self) -> None:
        use_cases, _, _, _ = make_use_cases()
        document = await use_cases.ingest_document(
            data=b"   ",
            filename="empty.txt",
            mime="text/plain",
            title=None,
            lang=None,
            source="upload",
            actor="test",
        )
        with pytest.raises(EmptyDocumentError):
            await use_cases.process_document(document.id)

    async def test_ocr_flag_propagates(self) -> None:
        def ocr_extract(data: bytes, mime: str) -> ParseResult:
            return ParseResult(text=data.decode("utf-8"), ocr_used=True)

        use_cases, _, _, _ = make_use_cases(extract=ocr_extract)
        document = await ingest_and_process(use_cases, THAI_TEXT, "scan")
        assert document.ocr_done is True


class TestSearch:
    async def test_hybrid_fuses_both_sides(self) -> None:
        use_cases, _, _, _ = make_use_cases()
        await ingest_and_process(use_cases, THAI_TEXT, "electric-quote")
        await ingest_and_process(use_cases, "สัญญาจ้างเหมางานประปา มูลค่า 320,000 บาท", "plumbing")
        results = await use_cases.search("ใบเสนอราคางานไฟฟ้า", mode="hybrid", limit=5)
        assert results.degraded is False
        assert results.results, "expected at least one hit"
        top = results.results[0]
        assert top.document_title == "electric-quote"
        assert "keyword" in top.matched_by and "semantic" in top.matched_by
        assert top.score > 0

    async def test_hybrid_degrades_without_embedder(self) -> None:
        use_cases, _, _, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        await ingest_and_process(use_cases, THAI_TEXT, "quote")
        results = await use_cases.search("ใบเสนอราคางานไฟฟ้า", mode="hybrid")
        assert results.degraded is True
        assert results.results
        assert results.results[0].matched_by == ("keyword",)

    async def test_hybrid_degrades_when_qdrant_down(self) -> None:
        # Indexing already degraded to keyword-only; search must too.
        use_cases, _, _, _ = make_use_cases(vector_index=BrokenVectorIndex())
        await ingest_and_process(use_cases, THAI_TEXT, "quote")
        results = await use_cases.search("ใบเสนอราคางานไฟฟ้า", mode="hybrid")
        assert results.degraded is True
        assert results.results

    async def test_semantic_mode_unavailable_is_degraded_and_empty(self) -> None:
        use_cases, _, _, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        await ingest_and_process(use_cases, THAI_TEXT, "quote")
        results = await use_cases.search("ไฟฟ้า", mode="semantic")
        assert results.degraded is True
        assert results.results == []

    async def test_keyword_mode_never_degraded(self) -> None:
        use_cases, _, _, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        await ingest_and_process(use_cases, THAI_TEXT, "quote")
        results = await use_cases.search("ไฟฟ้า", mode="keyword")
        assert results.degraded is False
        assert results.results
        assert results.results[0].matched_by == ("keyword",)

    async def test_snippet_truncated_to_400_chars(self) -> None:
        long_text = "คำค้นพิเศษ " + "รายละเอียดสัญญา " * 200
        use_cases, _, _, _ = make_use_cases()
        await ingest_and_process(use_cases, long_text, "long")
        results = await use_cases.search("คำค้นพิเศษ", mode="keyword")
        assert results.results
        assert len(results.results[0].text) <= SNIPPET_CHARS

    async def test_limit_caps_results(self) -> None:
        use_cases, _, _, _ = make_use_cases()
        for i in range(4):
            await ingest_and_process(use_cases, f"เอกสาร ทดสอบ ฉบับที่ {i}", f"doc-{i}")
        results = await use_cases.search("ทดสอบ", mode="hybrid", limit=2)
        assert len(results.results) == 2
