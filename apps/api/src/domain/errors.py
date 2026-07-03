"""Domain error hierarchy. Interface layer maps these to problem+json."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-rule violations."""


class CurrencyMismatchError(DomainError):
    """Arithmetic attempted between two different currencies."""


class DrawRuleError(DomainError):
    """Base class for contractor-draw rule violations."""


class NonPositiveAmountError(DrawRuleError):
    """A draw must be for a strictly positive amount."""


class DrawExceedsRemainingError(DrawRuleError):
    """A draw would exceed the remaining amount on its quotation."""


class PaidDrawImmutableError(DrawRuleError):
    """Paid draws are immutable and cannot be edited or cancelled."""


class DrawNotPayableError(DrawRuleError):
    """The draw is not in a payable state (already paid or cancelled)."""


class BankTransactionRuleError(DomainError):
    """A bank-transaction state transition the reconciliation rules forbid."""


class InvalidStageTransitionError(DomainError):
    """A lead stage transition that the pipeline does not allow."""


class InvalidScoreError(DomainError):
    """Intent score outside the 0-100 range."""


class InvalidCursorError(DomainError):
    """Pagination cursor could not be decoded."""


class InvalidImportanceError(DomainError):
    """Memory importance outside the 1-5 range."""
