"""Application-level errors (orchestration failures, not domain-rule breaks)."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application-layer failures."""


class NotFoundError(ApplicationError):
    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found")


class UnsupportedDocumentError(ApplicationError):
    """The uploaded document's mime type (or missing parser) cannot be handled."""

    def __init__(self, mime: str, detail: str | None = None) -> None:
        self.mime = mime
        super().__init__(
            detail
            or (
                f"Unsupported document type {mime!r}. Supported: text/plain, "
                "text/markdown, application/pdf, image/png, image/jpeg."
            )
        )


class EmptyDocumentError(ApplicationError):
    """Parsing succeeded but produced no indexable text."""

    def __init__(self) -> None:
        super().__init__(
            "No text could be extracted from the document. For scanned PDFs and "
            "images, OCR support (the 'parsing' extra plus tesseract-ocr-tha) "
            "must be installed."
        )


class ComplianceRefusedError(ApplicationError):
    """A source registration or fetch was refused by the compliance gate (§8.4).

    Structural, not conventional: facebook/OTA domains can never be registered.
    Maps to HTTP 422 with the violation reason in the detail (problems.py).
    """

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(f"Refused by compliance gate ({reason}): {detail}")


class LeadSourceInvalidError(ApplicationError):
    """A lead-source registration/update is structurally invalid (M5).

    Distinct from ComplianceRefusedError (§8.4 policy refusals): this covers
    shape problems — rss without a url, reddit without config.subreddit.
    Maps to HTTP 422 with a Thai-readable detail (problems.py).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class CollectorNotConfiguredError(ApplicationError):
    """A collector's credentials are missing (e.g. Reddit API keys).

    The discovery pipeline records 'skipped: no credentials' on the source
    and moves on — per §8.4 there is never a scrape-without-API fallback.
    """

    def __init__(self, source_type: str) -> None:
        self.source_type = source_type
        super().__init__(f"{source_type} collector is not configured (missing credentials)")


class UnrecognizedBankAlertError(ApplicationError):
    """Ingested text could not be parsed as a bank transaction alert."""

    def __init__(self) -> None:
        super().__init__(
            "Text was not recognized as a bank transaction alert. "
            "Supported alerts announce money moving in or out of an account "
            "(e.g. KBank, SCB, Bangkok Bank e-mail notifications); OTP, "
            "marketing, and balance-inquiry messages are rejected."
        )
