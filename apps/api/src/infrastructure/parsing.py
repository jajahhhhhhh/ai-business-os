"""Document text extraction: text/markdown, PDF (pdfplumber + OCR), images.

Optional dependencies (the `parsing` extra: pdfplumber, pytesseract,
pdf2image; plus the tesseract-ocr/tesseract-ocr-tha/poppler-utils system
packages) are imported lazily inside functions, so this module — and the
core import path — loads without them installed. Availability is probed via
importlib.util.find_spec; the probe and worker functions are module-level so
unit tests can monkeypatch them without any PDF/OCR library present.
"""

from __future__ import annotations

import importlib.util
import io

from src.application.errors import UnsupportedDocumentError
from src.application.ports import ParseResult

TEXT_MIMES = {"text/plain", "text/markdown"}
PDF_MIME = "application/pdf"
IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg"}

# Below this average of extracted characters per page, a PDF is assumed to be
# a scan (Thai quotations/receipts usually are) and OCR is attempted.
MIN_CHARS_PER_PAGE = 50
# Thai + English, matching the business's document mix.
OCR_LANG = "tha+eng"


def extract_text(data: bytes, mime: str) -> ParseResult:
    """Extract plain text from raw document bytes.

    Raises UnsupportedDocumentError for unknown mime types or when the
    required optional parser is not installed; the caller records the message
    on the document row (status='failed').
    """
    normalized = (mime or "").split(";")[0].strip().lower()
    if normalized in TEXT_MIMES:
        return ParseResult(text=_decode_text(data))
    if normalized == PDF_MIME:
        return _extract_pdf(data)
    if normalized in IMAGE_MIMES:
        return _extract_image(data, normalized)
    raise UnsupportedDocumentError(normalized or "unknown")


# ---------------------------------------------------------------- text


def _decode_text(data: bytes) -> str:
    """UTF-8 first (BOM-tolerant); legacy Thai TIS-620 as the fallback."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("tis-620")
    except UnicodeDecodeError:
        # Unknown legacy encoding: keep what is decodable rather than failing
        # the whole document.
        return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- pdf


def _pdf_available() -> bool:
    return importlib.util.find_spec("pdfplumber") is not None


def _ocr_available() -> bool:
    return (
        importlib.util.find_spec("pytesseract") is not None
        and importlib.util.find_spec("pdf2image") is not None
    )


def _image_ocr_available() -> bool:
    return (
        importlib.util.find_spec("pytesseract") is not None
        and importlib.util.find_spec("PIL") is not None
    )


def _pdf_page_texts(data: bytes) -> list[str]:
    import pdfplumber  # lazy: `parsing` extra

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _ocr_pdf(data: bytes) -> str:
    import pdf2image  # lazy: `parsing` extra
    import pytesseract

    images = pdf2image.convert_from_bytes(data)
    return "\n\n".join(pytesseract.image_to_string(image, lang=OCR_LANG) for image in images)


def _ocr_image(data: bytes) -> str:
    import pytesseract  # lazy: `parsing` extra
    from PIL import Image

    return pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang=OCR_LANG)


def _extract_pdf(data: bytes) -> ParseResult:
    if not _pdf_available():
        raise UnsupportedDocumentError(
            PDF_MIME,
            "PDF parsing requires pdfplumber — install the 'parsing' extra "
            "(pip install .[parsing]).",
        )
    pages = _pdf_page_texts(data)
    text = "\n\n".join(page for page in pages if page.strip()).strip()
    average_chars = sum(len(page) for page in pages) / len(pages) if pages else 0.0
    if pages and average_chars < MIN_CHARS_PER_PAGE and _ocr_available():
        return ParseResult(text=_ocr_pdf(data).strip(), ocr_used=True)
    return ParseResult(text=text)


# ---------------------------------------------------------------- images


def _extract_image(data: bytes, mime: str) -> ParseResult:
    if not _image_ocr_available():
        raise UnsupportedDocumentError(
            mime,
            "Image OCR requires pytesseract + Pillow — install the 'parsing' "
            "extra (pip install .[parsing]) and the tesseract-ocr-tha system package.",
        )
    return ParseResult(text=_ocr_image(data).strip(), ocr_used=True)
