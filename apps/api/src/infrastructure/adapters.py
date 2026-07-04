"""Construction of the KB/memory and competitor-intel gateway adapters.

Shared by the API factory (src/main.py) and the Celery worker (src/worker.py)
so the wiring exists in exactly one place.

Test seam: integration tests build KbAdapters / CompetitorAdapters out of
in-memory fakes (tests/fakes.py) and pass them to create_app(kb_adapters=...,
competitor_adapters=...). A constructor override was chosen over FastAPI
dependency_overrides because the worker pipelines and BackgroundTasks
fallbacks need the same injection point, and dependency_overrides only covers
HTTP request handling.

The optional collectors package (services/collectors) is imported LAZILY
inside ComplianceGateFetcher.fetch — same availability-gating philosophy as
BgeM3Embedder — so this module (and the whole API tree) imports cleanly when
collectors is not installed; sweeps then record per-source errors instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.errors import CollectorNotConfiguredError, ComplianceRefusedError
from src.application.lead_discovery import CollectedDoc
from src.application.ports import (
    ChangeAnalyst,
    Embedder,
    Fetcher,
    FetchPolicy,
    KeywordIndex,
    ObjectStorage,
    TextExtractor,
    VectorIndex,
)
from src.config import Settings
from src.infrastructure.change_analyst import (
    AgentRunRecorder,
    AnthropicChangeAnalyst,
    NullChangeAnalyst,
)
from src.infrastructure.embeddings import BgeM3Embedder
from src.infrastructure.keyword_index import MeilisearchKeywordIndex
from src.infrastructure.object_storage import S3ObjectStorage
from src.infrastructure.parsing import extract_text
from src.infrastructure.vector_index import QdrantVectorIndex


@dataclass(slots=True)
class KbAdapters:
    """The gateway set used by KB + memory use cases (fields are ports)."""

    storage: ObjectStorage
    keyword_index: KeywordIndex
    vector_index: VectorIndex
    embedder: Embedder
    extract: TextExtractor


def build_kb_adapters(settings: Settings) -> KbAdapters:
    return KbAdapters(
        storage=S3ObjectStorage(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_bucket,
        ),
        keyword_index=MeilisearchKeywordIndex(settings.meili_url, settings.meili_master_key),
        vector_index=QdrantVectorIndex(settings.qdrant_url),
        embedder=BgeM3Embedder(settings.embedding_model),
        extract=extract_text,
    )


# ------------------------------------------------------- M3: competitor intel


class ComplianceGateFetcher:
    """Fetcher port over collectors.compliance.ComplianceGate.

    The collectors import happens inside fetch (lazy, availability-gated):
    when the package is absent the fetch fails with a clear RuntimeError that
    the sweep records as a per-source 'error: ...' status. ComplianceViolation
    is translated to the application-level ComplianceRefusedError so the
    application layer never imports collectors.
    """

    def __init__(self) -> None:
        self._gate: Any | None = None

    async def fetch(self, policy: FetchPolicy, url: str) -> str:
        try:
            from collectors.compliance import (
                ComplianceGate,
                ComplianceViolation,
                SourcePolicy,
                TosPolicy,
            )
        except ImportError as exc:
            raise RuntimeError(
                "collectors package not installed; competitor sweeps need the "
                "services/collectors library (installed in the API container)"
            ) from exc
        if self._gate is None:
            self._gate = ComplianceGate()
        source_policy = SourcePolicy(
            name=policy.name,
            tos_policy=TosPolicy(policy.tos_policy),
            rate_limit_per_hr=policy.rate_limit_per_hr,
            enabled=policy.enabled,
        )
        try:
            return await self._gate.fetch(source_policy, url)
        except ComplianceViolation as exc:
            raise ComplianceRefusedError(exc.reason, str(exc)) from exc

    async def aclose(self) -> None:
        if self._gate is not None:
            await self._gate.aclose()


@dataclass(slots=True)
class CompetitorAdapters:
    """The gateway set used by the M3 competitor-intel use cases.

    `fetcher` is the compliance-gated fetcher — the ONLY path a sweep may use
    for outbound HTTP. `analyst` is the LLM port; wired to NullChangeAnalyst
    when no API key is configured.
    """

    storage: ObjectStorage
    fetcher: Fetcher
    analyst: ChangeAnalyst

    async def aclose(self) -> None:
        """Release HTTP clients (app lifespan / worker teardown)."""
        for gateway in (self.fetcher, self.analyst):
            aclose = getattr(gateway, "aclose", None)
            if aclose is not None:
                await aclose()


# --------------------------------------------------------- M5: lead discovery


class ComplianceLeadCollector:
    """LeadCollector port building a per-source collector (rss/reddit).

    Same lazy-import availability gating as ComplianceGateFetcher: the
    collectors package is only imported inside collect(), so the API tree
    stays importable without it and lead sweeps then record per-source
    'error: ...' statuses. Reddit uses the OFFICIAL API only (§8.4): missing
    credentials raise CollectorNotConfiguredError, which the pipeline records
    as 'skipped: no credentials' — never an HTML-scrape fallback.
    """

    def __init__(self, *, reddit_client_id: str = "", reddit_client_secret: str = "") -> None:
        self._reddit_client_id = reddit_client_id
        self._reddit_client_secret = reddit_client_secret
        self._gate: Any | None = None

    async def collect(self, source: Any) -> list[CollectedDoc]:
        try:
            from collectors.compliance import (
                ComplianceGate,
                ComplianceViolation,
                SourcePolicy,
                TosPolicy,
            )
            from collectors.reddit import RedditCollector
            from collectors.rss import RssCollector
        except ImportError as exc:
            raise RuntimeError(
                "collectors package not installed; lead collection needs the "
                "services/collectors library (installed in the API container)"
            ) from exc
        if self._gate is None:
            self._gate = ComplianceGate()
        policy = SourcePolicy(
            name=str(source.id),
            tos_policy=TosPolicy(source.tos_policy),
            rate_limit_per_hr=source.rate_limit_per_hr,
            enabled=source.enabled,
        )
        if source.type == "reddit":
            config = source.config_json or {}
            collector: Any = RedditCollector(
                self._gate,
                policy,
                str(config.get("subreddit") or ""),
                config.get("query") or None,
                client_id=self._reddit_client_id,
                client_secret=self._reddit_client_secret,
            )
            if not collector.is_configured:
                raise CollectorNotConfiguredError("reddit")
        elif source.type == "rss":
            if not source.url:
                raise RuntimeError("rss lead source has no url")
            collector = RssCollector(self._gate, policy, source.url)
        else:
            raise RuntimeError(f"unsupported lead source type {source.type!r}")
        try:
            raw_docs = await collector.fetch()
        except ComplianceViolation as exc:
            raise ComplianceRefusedError(exc.reason, str(exc)) from exc
        return [
            CollectedDoc(url=doc.url, content=doc.content, fetched_at=doc.fetched_at)
            for doc in raw_docs
        ]

    async def aclose(self) -> None:
        if self._gate is not None:
            await self._gate.aclose()


def build_lead_collector(settings: Settings) -> ComplianceLeadCollector:
    return ComplianceLeadCollector(
        reddit_client_id=settings.reddit_client_id,
        reddit_client_secret=settings.reddit_client_secret,
    )


def build_competitor_adapters(
    settings: Settings, maker: async_sessionmaker[AsyncSession]
) -> CompetitorAdapters:
    analyst: ChangeAnalyst
    if settings.anthropic_api_key:
        analyst = AnthropicChangeAnalyst(
            api_key=settings.anthropic_api_key,
            model=settings.change_analyst_model,
            daily_budget_usd=settings.llm_daily_budget_usd,
            recorder=AgentRunRecorder(maker),
        )
    else:
        analyst = NullChangeAnalyst()
    return CompetitorAdapters(
        storage=S3ObjectStorage(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_bucket,
        ),
        fetcher=ComplianceGateFetcher(),
        analyst=analyst,
    )
