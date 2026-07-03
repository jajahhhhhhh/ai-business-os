"""Memory use cases against fakes: recall fusion + consolidation rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.memory import MEMORY_COLLECTION, MemoryUseCases
from src.application.ports import VectorIndex
from src.domain.errors import InvalidImportanceError
from tests.fakes import (
    BrokenVectorIndex,
    FakeEmbedder,
    FakeMemoryRepository,
    InMemoryVectorIndex,
    NullAuditWriter,
)


def make_use_cases(
    *, embedder: FakeEmbedder | None = None, vector_index: VectorIndex | None = None
) -> tuple[MemoryUseCases, FakeMemoryRepository, Any]:
    repo = FakeMemoryRepository()
    vector = vector_index if vector_index is not None else InMemoryVectorIndex()
    use_cases = MemoryUseCases(
        repo,
        NullAuditWriter(),
        vector_index=vector,
        embedder=embedder if embedder is not None else FakeEmbedder(available=True),
    )
    return use_cases, repo, vector


class TestRemember:
    async def test_remember_embeds_when_available(self) -> None:
        use_cases, repo, vector = make_use_cases()
        row = await use_cases.remember(
            kind="business",
            subject="MR.HOME draw terms",
            body="งวดที่ 1 ร้อยละ 30 เมื่อเริ่มงาน",
            importance=4,
            actor="test",
        )
        assert row.embedding_point_id == str(row.id)
        assert str(row.id) in vector.collections[MEMORY_COLLECTION]

    async def test_remember_without_embedder_still_persists(self) -> None:
        use_cases, repo, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        row = await use_cases.remember(
            kind="person", subject="J", body="Owner, Thai output", actor="test"
        )
        assert row.embedding_point_id is None
        assert row.id in repo.memories

    async def test_qdrant_down_does_not_break_remember(self) -> None:
        use_cases, repo, _ = make_use_cases(vector_index=BrokenVectorIndex())
        row = await use_cases.remember(
            kind="decision", subject="No reranker in M2", body="RRF only", actor="test"
        )
        assert row.id in repo.memories
        assert row.embedding_point_id is None

    async def test_importance_out_of_range_rejected(self) -> None:
        use_cases, _, _ = make_use_cases()
        with pytest.raises(InvalidImportanceError):
            await use_cases.remember(
                kind="task", subject="s", body="b", importance=6, actor="test"
            )


class TestRecall:
    async def test_recall_fuses_text_and_semantic(self) -> None:
        use_cases, _, _ = make_use_cases()
        target = await use_cases.remember(
            kind="business",
            subject="ค่าไฟฟ้าวิลล่าลิปะน้อย",
            body="งบงานไฟฟ้า 450,000 บาท",
            actor="test",
        )
        await use_cases.remember(
            kind="business", subject="งานประปา", body="งบ 320,000 บาท", actor="test"
        )
        hits = await use_cases.recall("ไฟฟ้า")
        assert hits
        assert hits[0].memory.id == target.id
        assert hits[0].score > 0

    async def test_recall_text_only_when_embedder_unavailable(self) -> None:
        use_cases, _, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        row = await use_cases.remember(
            kind="business", subject="Meili master key rotated", body="2026-07", actor="test"
        )
        hits = await use_cases.recall("master key")
        assert [hit.memory.id for hit in hits] == [row.id]

    async def test_recall_excludes_expired(self) -> None:
        use_cases, repo, _ = make_use_cases()
        row = await use_cases.remember(
            kind="task",
            subject="follow up pool contractor",
            body="call",
            expires_at=datetime.now(UTC) - timedelta(days=1),
            actor="test",
        )
        assert row.id in repo.memories
        hits = await use_cases.recall("pool contractor")
        assert hits == []

    async def test_recall_excludes_consolidated(self) -> None:
        use_cases, repo, _ = make_use_cases()
        keep = await use_cases.remember(
            kind="business", subject="ผู้รับเหมา MR.HOME", body="งวดเบิก 30/40/30", actor="t"
        )
        merged = await use_cases.remember(
            kind="business", subject="ผู้รับเหมา MR.HOME", body="งวดเบิก 30/40/30", actor="t"
        )
        repo.memories[merged.id].consolidated_into = keep.id
        hits = await use_cases.recall("MR.HOME")
        assert [hit.memory.id for hit in hits] == [keep.id]

    async def test_recall_kind_filter(self) -> None:
        use_cases, _, _ = make_use_cases()
        await use_cases.remember(kind="person", subject="agent Bob", body="x", actor="t")
        task = await use_cases.remember(kind="task", subject="email Bob", body="y", actor="t")
        hits = await use_cases.recall("Bob", kind="task")
        assert [hit.memory.id for hit in hits] == [task.id]


class TestConsolidate:
    async def test_merges_duplicates_keeps_highest_importance(self) -> None:
        use_cases, repo, vector = make_use_cases()
        low = await use_cases.remember(
            kind="business", subject="งวดเบิก MR.HOME", body="30/40/30", importance=2, actor="t"
        )
        high = await use_cases.remember(
            kind="business", subject="งวดเบิก MR.HOME", body="30/40/30", importance=5, actor="t"
        )
        result = await use_cases.consolidate("test")
        assert result.merged == 1
        assert repo.memories[low.id].consolidated_into == high.id
        assert repo.memories[high.id].consolidated_into is None
        # loser's vector point removed, survivor's kept
        assert str(low.id) not in vector.collections[MEMORY_COLLECTION]
        assert str(high.id) in vector.collections[MEMORY_COLLECTION]

    async def test_importance_tie_keeps_newest(self) -> None:
        use_cases, repo, _ = make_use_cases()
        older = await use_cases.remember(
            kind="decision", subject="ราคาห้องพัก", body="4500 บาท/คืน", importance=3, actor="t"
        )
        repo.memories[older.id].created_at -= timedelta(days=7)
        newer = await use_cases.remember(
            kind="decision", subject="ราคาห้องพัก", body="4500 บาท/คืน", importance=3, actor="t"
        )
        result = await use_cases.consolidate("test")
        assert result.merged == 1
        assert repo.memories[older.id].consolidated_into == newer.id

    async def test_never_merges_across_kinds(self) -> None:
        use_cases, repo, _ = make_use_cases()
        await use_cases.remember(kind="business", subject="same text", body="same", actor="t")
        await use_cases.remember(kind="person", subject="same text", body="same", actor="t")
        result = await use_cases.consolidate("test")
        assert result.merged == 0

    async def test_dissimilar_memories_not_merged(self) -> None:
        use_cases, _, _ = make_use_cases()
        await use_cases.remember(
            kind="business", subject="งานไฟฟ้า", body="450,000 บาท", actor="t"
        )
        await use_cases.remember(
            kind="business", subject="Reddit lead sweep cadence", body="every 4h", actor="t"
        )
        result = await use_cases.consolidate("test")
        assert result.merged == 0

    async def test_exact_subject_grouping_without_embedder(self) -> None:
        use_cases, repo, _ = make_use_cases(embedder=FakeEmbedder(available=False))
        a = await use_cases.remember(
            kind="business", subject="dup subject", body="v1", importance=1, actor="t"
        )
        b = await use_cases.remember(
            kind="business", subject="dup subject", body="v2 (different body)",
            importance=4, actor="t",
        )
        await use_cases.remember(kind="business", subject="unique", body="v", actor="t")
        result = await use_cases.consolidate("test")
        assert result.merged == 1
        assert repo.memories[a.id].consolidated_into == b.id

    async def test_expired_memories_hard_deleted_with_points(self) -> None:
        use_cases, repo, vector = make_use_cases()
        expired = await use_cases.remember(
            kind="task",
            subject="temporary note",
            body="obsolete",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            actor="t",
        )
        kept = await use_cases.remember(kind="task", subject="still valid", body="x", actor="t")
        result = await use_cases.consolidate("test")
        assert result.expired == 1
        assert expired.id not in repo.memories
        assert kept.id in repo.memories
        assert str(expired.id) not in vector.collections[MEMORY_COLLECTION]

    async def test_counts_are_zero_on_clean_store(self) -> None:
        use_cases, _, _ = make_use_cases()
        result = await use_cases.consolidate("test")
        assert (result.merged, result.expired) == (0, 0)
