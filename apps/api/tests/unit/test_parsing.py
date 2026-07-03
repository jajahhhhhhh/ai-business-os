"""Parsing dispatch without any PDF/OCR library installed.

PDF and image paths are exercised by monkeypatching the module-level
availability probes and worker functions in src/infrastructure/parsing.py —
that is exactly why they are module-level.
"""

from __future__ import annotations

import pytest

from src.application.errors import UnsupportedDocumentError
from src.infrastructure import parsing
from src.infrastructure.parsing import extract_text

THAI = "ใบเสนอราคางานรีโนเวท จำนวน 450,000 บาท"


class TestText:
    def test_plain_utf8(self) -> None:
        result = extract_text(THAI.encode("utf-8"), "text/plain")
        assert result.text == THAI
        assert result.ocr_used is False

    def test_markdown_utf8(self) -> None:
        result = extract_text(b"# Heading\n\nbody", "text/markdown")
        assert result.text == "# Heading\n\nbody"

    def test_mime_parameters_ignored(self) -> None:
        result = extract_text(b"hello", "text/plain; charset=utf-8")
        assert result.text == "hello"

    def test_tis620_fallback(self) -> None:
        data = THAI.encode("tis-620")  # invalid as UTF-8
        with pytest.raises(UnicodeDecodeError):
            data.decode("utf-8")
        result = extract_text(data, "text/plain")
        assert result.text == THAI
        assert result.ocr_used is False

    def test_utf8_bom_stripped(self) -> None:
        result = extract_text(b"\xef\xbb\xbfhello", "text/plain")
        assert result.text == "hello"


class TestUnsupported:
    def test_unknown_mime_raises(self) -> None:
        with pytest.raises(UnsupportedDocumentError) as excinfo:
            extract_text(b"...", "application/zip")
        assert "application/zip" in str(excinfo.value)

    def test_image_without_pytesseract_raises_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(parsing, "_image_ocr_available", lambda: False)
        with pytest.raises(UnsupportedDocumentError) as excinfo:
            extract_text(b"\x89PNG...", "image/png")
        assert "parsing" in str(excinfo.value)  # points at the extra to install

    def test_pdf_without_pdfplumber_raises_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(parsing, "_pdf_available", lambda: False)
        with pytest.raises(UnsupportedDocumentError) as excinfo:
            extract_text(b"%PDF-1.7", "application/pdf")
        assert "pdfplumber" in str(excinfo.value)


class TestPdfDispatch:
    def test_text_pdf_skips_ocr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = ["A" * 200, "B" * 200]  # plenty of text per page
        monkeypatch.setattr(parsing, "_pdf_available", lambda: True)
        monkeypatch.setattr(parsing, "_ocr_available", lambda: True)
        monkeypatch.setattr(parsing, "_pdf_page_texts", lambda data: pages)
        monkeypatch.setattr(
            parsing, "_ocr_pdf", lambda data: pytest.fail("OCR must not run")
        )
        result = extract_text(b"%PDF", "application/pdf")
        assert result.ocr_used is False
        assert "A" * 200 in result.text and "B" * 200 in result.text

    def test_scanned_pdf_falls_back_to_ocr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(parsing, "_pdf_available", lambda: True)
        monkeypatch.setattr(parsing, "_ocr_available", lambda: True)
        monkeypatch.setattr(parsing, "_pdf_page_texts", lambda data: ["", " "])
        monkeypatch.setattr(parsing, "_ocr_pdf", lambda data: THAI)
        result = extract_text(b"%PDF", "application/pdf")
        assert result.ocr_used is True
        assert result.text == THAI

    def test_scanned_pdf_without_ocr_returns_sparse_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # OCR unavailable: the sparse extraction is returned as-is; the use
        # case then fails the document with EmptyDocumentError if empty.
        monkeypatch.setattr(parsing, "_pdf_available", lambda: True)
        monkeypatch.setattr(parsing, "_ocr_available", lambda: False)
        monkeypatch.setattr(parsing, "_pdf_page_texts", lambda data: ["", ""])
        result = extract_text(b"%PDF", "application/pdf")
        assert result.ocr_used is False
        assert result.text == ""


class TestImageDispatch:
    def test_image_ocr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(parsing, "_image_ocr_available", lambda: True)
        monkeypatch.setattr(parsing, "_ocr_image", lambda data: f" {THAI} ")
        result = extract_text(b"\xff\xd8...", "image/jpeg")
        assert result.ocr_used is True
        assert result.text == THAI
