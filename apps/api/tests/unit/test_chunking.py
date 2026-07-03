"""Thai/EN-aware chunker: sizes, boundaries, overlap continuity, determinism."""

from __future__ import annotations

import pytest

from src.domain.chunking import Chunk, chunk_text

THAI_QUOTE = (
    "ใบเสนอราคางานรีโนเวทวิลล่า ลิปะน้อย เกาะสมุย  "
    "งานไฟฟ้าทั้งหมดรวมค่าแรงและอุปกรณ์ จำนวนเงิน 450,000 บาท  "
    "งานประปารวมสุขภัณฑ์ 320,000 บาท  "
    "กำหนดเบิกงวดที่ 1 เมื่อเริ่มงาน ร้อยละ 30 ฯลฯ "
)


class TestSingleChunk:
    def test_short_text_is_one_chunk(self) -> None:
        assert chunk_text("hello world") == [Chunk(seq=0, text="hello world")]

    def test_exact_boundary_is_one_chunk(self) -> None:
        text = "x" * 1800
        assert chunk_text(text) == [Chunk(seq=0, text=text)]

    def test_empty_and_whitespace_yield_no_chunks(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("  \n\n \t ") == []


class TestEnglish:
    def test_sentences_pack_up_to_target(self) -> None:
        text = ". ".join(f"Sentence number {i} of the contract" for i in range(60)) + "."
        chunks = chunk_text(text, target_chars=200, overlap_chars=40)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= 200 for chunk in chunks)
        assert all(chunk.text.strip() for chunk in chunks)
        assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))

    def test_overlap_continuity(self) -> None:
        text = ". ".join(f"Sentence number {i} of the contract" for i in range(60)) + "."
        chunks = chunk_text(text, target_chars=200, overlap_chars=40)
        for previous, current in zip(chunks, chunks[1:], strict=False):
            # The overlap prefix of each chunk is taken verbatim from the end
            # of the previous chunk.
            first_word = current.text.split()[0]
            assert first_word in previous.text

    def test_zero_overlap_supported(self) -> None:
        text = ". ".join(f"Sentence {i}" for i in range(80)) + "."
        chunks = chunk_text(text, target_chars=100, overlap_chars=0)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= 100 for chunk in chunks)


class TestThai:
    def test_thai_space_clusters_split(self) -> None:
        chunks = chunk_text(THAI_QUOTE * 30, target_chars=400, overlap_chars=80)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= 400 for chunk in chunks)
        assert all(chunk.text.strip() for chunk in chunks)

    def test_unbroken_thai_run_hard_slices_within_target(self) -> None:
        run = "สัญญาจ้างเหมาก่อสร้างบ้านพักตากอากาศ" * 100  # no whitespace at all
        chunks = chunk_text(run, target_chars=300, overlap_chars=50)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= 300 for chunk in chunks)


class TestMixedAndStructure:
    def test_mixed_thai_english_document(self) -> None:
        text = (
            "Quotation for Lipa Noi villa.\n\n"
            "งานไฟฟ้า 450,000 บาท\nงานประปา 320,000 บาท\n\n"
            "Total: 770,000 THB"
        )
        chunks = chunk_text(text)
        assert len(chunks) == 1
        # Paragraph and line structure preserved when nothing needs splitting.
        assert "งานไฟฟ้า 450,000 บาท\nงานประปา 320,000 บาท" in chunks[0].text
        assert "Quotation for Lipa Noi villa.\n\nงานไฟฟ้า" in chunks[0].text

    def test_lines_never_split_when_they_fit(self) -> None:
        text = "\n".join(f"line {i} " + "ข้อความ" * 5 for i in range(50))
        chunks = chunk_text(text, target_chars=300, overlap_chars=0)
        for chunk in chunks:
            for line in chunk.text.split("\n"):
                assert line.startswith("line ")

    def test_deterministic(self) -> None:
        text = THAI_QUOTE * 20
        assert chunk_text(text, 400, 80) == chunk_text(text, 400, 80)

    def test_invalid_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            chunk_text("x", target_chars=0)
