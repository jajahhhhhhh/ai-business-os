"""Collector contract shared by all source-specific collectors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawDocument:
    """A normalized fetched artifact, ready for the ingestion pipeline.

    ``content_hash`` is the dedup key (§8.1): identical content fetched twice
    is dropped before it ever reaches the extractor.
    """

    source_name: str
    url: str
    content: str
    content_type: str = "text/plain"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class Collector(Protocol):
    """One collector per source type (rss, gmaps_api, reddit_api, ...).

    Implementations receive a gated fetch callable from the ComplianceGate;
    they must not construct their own HTTP clients.
    """

    source_name: str

    async def fetch(self) -> list[RawDocument]: ...
