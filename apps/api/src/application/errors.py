"""Application-level errors (orchestration failures, not domain-rule breaks)."""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application-layer failures."""


class NotFoundError(ApplicationError):
    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found")


class UnrecognizedBankAlertError(ApplicationError):
    """Ingested text could not be parsed as a bank transaction alert."""

    def __init__(self) -> None:
        super().__init__(
            "Text was not recognized as a bank transaction alert. "
            "Supported alerts announce money moving in or out of an account "
            "(e.g. KBank, SCB, Bangkok Bank e-mail notifications); OTP, "
            "marketing, and balance-inquiry messages are rejected."
        )
