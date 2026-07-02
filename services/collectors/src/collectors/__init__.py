"""Compliance-gated data collectors.

Every fetch passes through :class:`collectors.compliance.ComplianceGate`.
Collectors never call the network directly — they receive a gated fetch function.
"""

from collectors.base import Collector, RawDocument
from collectors.compliance import ComplianceGate, ComplianceViolation, SourcePolicy

__all__ = [
    "Collector",
    "RawDocument",
    "ComplianceGate",
    "ComplianceViolation",
    "SourcePolicy",
]
