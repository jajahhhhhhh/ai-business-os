"""Lead discovery use cases (M5): source registry CRUD + the §8.1 pipeline.

Registry (LeadSourceUseCases): generic lead sources (sources rows with
competitor_id IS NULL) of type 'rss' or 'reddit'. Compliance is enforced in
code, not by convention (§8.4): rss URLs pass the same HARD_BLOCKLIST check
as competitor sources (facebook/OTA domains are structurally impossible),
reddit sources carry only a subreddit name — collection goes through the
official API.

Pipeline (LeadDiscoveryUseCases): collect -> raw_documents (deduped by
(source_id, content_hash)) -> prefilter (pure, zero LLM spend for noise) ->
classify+score (LLM batches of <=10 with a deterministic §8.3 fallback) ->
persist (exact dedup_hash + semantic >=0.92 dedup, encrypted PDPA-minimal
contact, lead_events + lead_scores).

NFR-1: one bad source/document never stops the rest — per-source outcomes
land in sources.last_status ('ok: N docs, M leads' | 'blocked: ...' |
'error: ...' | 'skipped: no credentials') and discover_all never raises.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import structlog

from src.application.competitor_intel import check_url_compliance
from src.application.errors import (
    CollectorNotConfiguredError,
    ComplianceRefusedError,
    LeadSourceInvalidError,
    NotFoundError,
)
from src.application.ports import Embedder, ObjectStorage, VectorIndex, VectorPoint
from src.application.repositories import (
    AuditWriter,
    LeadDiscoveryRepository,
    LeadRow,
    LeadSourceRepository,
    LeadSourceRow,
)
from src.domain.lead_signals import (
    LEAD_KINDS,
    classify_kind,
    content_sha256,
    detect_language,
    excerpt,
    is_candidate,
    lead_dedup_hash,
    parse_contact,
    score_signals,
)
from src.domain.leads import IntentScore
from src.infrastructure.prompts import render_prompt

logger = structlog.get_logger("application.lead_discovery")

LEAD_SOURCE_TYPES = ("rss", "reddit")
DEFAULT_LEAD_RATE_LIMIT_PER_HR = 12

STATUS_DETAIL_MAX_CHARS = 120
SKIPPED_NO_CREDENTIALS = "skipped: no credentials"

CLASSIFY_BATCH_SIZE = 10
CLASSIFY_MAX_TOKENS = 1500
CLASSIFY_ITEM_MAX_CHARS = 1500
MODEL_VERSION_LLM = "llm-v1"
MODEL_VERSION_RULES = "rules-v1"

LEADS_COLLECTION = "leads"
SEMANTIC_DUP_THRESHOLD = 0.92
SEMANTIC_WINDOW_DAYS = 60

RAW_STATUS_NOISE = "noise"
RAW_STATUS_CANDIDATE = "candidate"
RAW_STATUS_LEAD = "lead"
RAW_STATUS_DUPLICATE = "duplicate"

RSS_URL_REQUIRED_TH = "แหล่งข้อมูลแบบ RSS ต้องระบุ url ของฟีด (เช่น https://example.com/feed.xml)"
REDDIT_SUBREDDIT_REQUIRED_TH = (
    'แหล่งข้อมูลแบบ Reddit ต้องระบุ config.subreddit (เช่น {"subreddit": "kohsamui"})'
)
SUBREDDIT_INVALID_TH = "ชื่อ subreddit ไม่ถูกต้อง: {value!r} — ใช้ได้เฉพาะตัวอักษร ตัวเลข และ _"

_SUBREDDIT_RE = re.compile(r"[A-Za-z0-9_]{2,50}")

# Inline fallback for packages/prompts/customer-discovery/classify.th.j2.
# Required template variables: items — a list of {index: int, text: str}.
CLASSIFY_PROMPT_FALLBACK_TH = (
    "คุณเป็นผู้ช่วยคัดกรองลูกค้ามุ่งหวัง (lead) ของธุรกิจวิลล่าให้เช่าบนเกาะสมุย\n"
    "พิจารณาโพสต์สาธารณะต่อไปนี้ทีละรายการ:\n\n"
    "{% for item in items %}[{{ item.index }}]\n{{ item.text }}\n---\n{% endfor %}\n"
    "ตอบเป็น JSON array เท่านั้น ห้ามมีข้อความอื่น รูปแบบต่อรายการ:\n"
    '{"index": <เลขรายการ>, "is_lead": true|false, '
    '"kind": "guest"|"longstay"|"b2b"|"supplier", '
    '"intent_score": 0-100, "language": "th"|"en", '
    '"suggestion": "คำแนะนำติดตามผลภาษาไทย 1 ประโยค"}\n'
    "- is_lead: true เมื่อผู้เขียนน่าจะเป็นลูกค้า/พาร์ตเนอร์ที่ติดต่อได้จริง "
    "ไม่ใช่โฆษณา ข่าว หรือคำถามทั่วไป\n"
    "- kind: guest = นักท่องเที่ยวหาที่พัก, longstay = ผู้เช่ารายเดือน/ดิจิทัลนอมัด, "
    "b2b = ผู้จัดรีทรีต/ช่างภาพ/ตัวแทน, supplier = ผู้รับเหมา/ซัพพลายเออร์งานรีโนเวท\n"
    "- intent_score: ความชัดเจนและความเร่งด่วนของความต้องการ (0-100)"
)


def _clip_status(prefix: str, detail: str) -> str:
    return f"{prefix}{detail[:STATUS_DETAIL_MAX_CHARS]}"


# ------------------------------------------------------------------- ports


@dataclass(frozen=True, slots=True)
class CollectedDoc:
    """One normalized document returned by a lead collector."""

    url: str
    content: str
    fetched_at: datetime


class LeadCollector(Protocol):
    """Collection seam: production builds Rss/Reddit collectors from the
    source row (infrastructure/adapters.py, collectors imported lazily);
    tests inject a fake. Raises CollectorNotConfiguredError when credentials
    are missing and ComplianceRefusedError when the gate refuses."""

    async def collect(self, source: LeadSourceRow) -> list[CollectedDoc]: ...


class CompletionLike(Protocol):
    """Structural mirror of agents.ports.LlmCompletion (no import cycle)."""

    @property
    def text(self) -> str: ...
    @property
    def tokens_in(self) -> int: ...
    @property
    def tokens_out(self) -> int: ...
    @property
    def cost_usd(self) -> Decimal: ...
    @property
    def model(self) -> str: ...


class LeadLlm(Protocol):
    """Structural mirror of agents.ports.AgentLlm: None = fall back to rules."""

    async def complete(
        self,
        *,
        tier: str,
        prompt: str,
        max_tokens: int,
        system: str | None = None,
    ) -> CompletionLike | None: ...


class ContactCipher(Protocol):
    """PII seam (infrastructure/pii.py PiiCipher in production)."""

    def encrypt_contact(self, contact: dict[str, Any] | None) -> dict[str, Any] | None: ...
    def decrypt_contact(self, value: object) -> dict[str, Any] | None: ...


# -------------------------------------------------------------- validation


def normalize_subreddit(value: object) -> str:
    """'r/KohSamui/' -> 'kohsamui'; raises LeadSourceInvalidError when unusable."""
    if not isinstance(value, str) or not value.strip():
        raise LeadSourceInvalidError(REDDIT_SUBREDDIT_REQUIRED_TH)
    cleaned = value.strip().removeprefix("/r/").removeprefix("r/").strip("/").lower()
    if not _SUBREDDIT_RE.fullmatch(cleaned):
        raise LeadSourceInvalidError(SUBREDDIT_INVALID_TH.format(value=value))
    return cleaned


def validate_lead_source(
    type_: str, url: str | None, config: dict[str, Any] | None
) -> tuple[str | None, dict[str, Any] | None]:
    """Validate + normalize (url, config) for a lead source (§8.4 enforced).

    rss: url required and blocklist-checked (ComplianceRefusedError -> 422).
    reddit: config.subreddit required, normalized ('r/' stripped, lowercase);
    the optional config.query is kept verbatim.
    """
    if type_ not in LEAD_SOURCE_TYPES:
        raise LeadSourceInvalidError(f"source type {type_!r} not allowed (rss|reddit)")
    if type_ == "rss":
        if not url:
            raise LeadSourceInvalidError(RSS_URL_REQUIRED_TH)
        check_url_compliance(url)
        return url, config
    # reddit
    config = dict(config or {})
    config["subreddit"] = normalize_subreddit(config.get("subreddit"))
    query = config.get("query")
    config["query"] = query if isinstance(query, str) and query.strip() else None
    return url, {"subreddit": config["subreddit"], "query": config["query"]}


# ---------------------------------------------------------------- registry


class LeadSourceUseCases:
    def __init__(self, repo: LeadSourceRepository, audit: AuditWriter) -> None:
        self._repo = repo
        self._audit = audit

    async def list_sources(self) -> Sequence[LeadSourceRow]:
        return await self._repo.list_lead_sources()

    async def _get_lead_source(self, source_id: uuid.UUID) -> LeadSourceRow:
        source = await self._repo.get_source(source_id)
        if source is None or source.competitor_id is not None:
            # Competitor-owned sources are managed under /v1/competitors.
            raise NotFoundError("source", source_id)
        return source

    async def get_lead_source(self, source_id: uuid.UUID) -> LeadSourceRow:
        return await self._get_lead_source(source_id)

    async def create_source(
        self,
        *,
        name: str,
        type: str,  # noqa: A002 - mirrors the column name
        url: str | None,
        config: dict[str, Any] | None,
        rate_limit_per_hr: int,
        actor: str,
    ) -> LeadSourceRow:
        url, config = validate_lead_source(type, url, config)
        source = await self._repo.create_lead_source(
            name=name, type=type, url=url, config=config, rate_limit_per_hr=rate_limit_per_hr
        )
        await self._audit.write(
            actor,
            "lead_source.registered",
            "sources",
            source.id,
            {"name": name, "type": type, "url": url, "config": config},
        )
        return source

    async def update_source(
        self, source_id: uuid.UUID, changes: dict[str, Any], actor: str
    ) -> LeadSourceRow:
        source = await self._get_lead_source(source_id)
        applied = dict(changes)
        if "url" in applied:
            if source.type == "rss":
                if not applied["url"]:
                    raise LeadSourceInvalidError(RSS_URL_REQUIRED_TH)
                check_url_compliance(applied["url"])  # blocklist re-check (§8.4)
            elif applied["url"]:
                check_url_compliance(applied["url"])
        if "config" in applied:
            if source.type == "reddit":
                _, applied["config"] = validate_lead_source("reddit", None, applied["config"])
            applied["config_json"] = applied.pop("config")
        updated = await self._repo.update_source(source_id, applied)
        await self._audit.write(
            actor,
            "lead_source.updated",
            "sources",
            source_id,
            {key: value for key, value in applied.items() if key != "config"},
        )
        return updated

    async def delete_source(self, source_id: uuid.UUID, actor: str) -> None:
        await self._get_lead_source(source_id)
        await self._repo.delete_source(source_id)
        await self._audit.write(actor, "lead_source.removed", "sources", source_id, None)


# ---------------------------------------------------------------- pipeline


@dataclass
class DiscoveryStats:
    """Per-run pipeline counters + LLM usage (booked by the agent runner)."""

    sources: int = 0
    docs: int = 0
    new_docs: int = 0
    candidates: int = 0
    leads: int = 0
    duplicates: int = 0
    noise: int = 0
    skipped: int = 0
    blocked: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources": self.sources,
            "docs": self.docs,
            "new_docs": self.new_docs,
            "candidates": self.candidates,
            "leads": self.leads,
            "duplicates": self.duplicates,
            "noise": self.noise,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "errors": self.errors,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": str(self.cost_usd),
        }


@dataclass(frozen=True, slots=True)
class LeadVerdict:
    """Classification outcome for one candidate (LLM or rules)."""

    is_lead: bool
    kind: str
    intent_score: int
    language: str
    suggestion: str | None
    model_version: str
    features: dict[str, Any]


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_classification_batch(text: str, count: int) -> dict[int, dict[str, Any]] | None:
    """Defensively parse the LLM's JSON array -> {index: entry}.

    Tolerates markdown code fences and prose around the array. Returns None
    when no usable array is found; entries with out-of-range/duplicate
    indexes or a non-dict shape are dropped (their items fall back to rules).
    """
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    entries: dict[int, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        if not 0 <= index < count or index in entries:
            continue
        entries[index] = item
    return entries


def _verdict_from_llm(entry: dict[str, Any], doc: CollectedDoc, now: datetime) -> LeadVerdict:
    """Coerce one LLM entry into a LeadVerdict (defensive on every field)."""
    kind = entry.get("kind")
    if kind not in LEAD_KINDS:
        kind = classify_kind(doc.content)
    raw_score = entry.get("intent_score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, int | float):
        raw_score = _rules_verdict(doc, now).intent_score
    score = IntentScore.clamped(raw_score).value
    language = entry.get("language")
    if not isinstance(language, str) or language.lower() not in ("th", "en"):
        language = detect_language(doc.content)
    suggestion = entry.get("suggestion")
    if not isinstance(suggestion, str) or not suggestion.strip():
        suggestion = None
    return LeadVerdict(
        is_lead=bool(entry.get("is_lead")),
        kind=str(kind),
        intent_score=score,
        language=language.lower(),
        suggestion=suggestion,
        model_version=MODEL_VERSION_LLM,
        features={
            "source": "llm",
            "is_lead": bool(entry.get("is_lead")),
            "kind": str(kind),
            "intent_score": score,
            "language": language.lower(),
        },
    )


def _rules_verdict(doc: CollectedDoc, now: datetime) -> LeadVerdict:
    score, features = score_signals(doc.content, fetched_at=doc.fetched_at, now=now)
    return LeadVerdict(
        is_lead=True,  # prefiltered candidates default to lead under the rules path
        kind=str(features["kind"]),
        intent_score=score,
        language=str(features["language"]),
        suggestion=None,
        model_version=MODEL_VERSION_RULES,
        features=features,
    )


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class LeadDiscoveryUseCases:
    def __init__(
        self,
        repo: LeadDiscoveryRepository,
        audit: AuditWriter,
        *,
        storage: ObjectStorage,
        collector: LeadCollector,
        pii: ContactCipher,
        embedder: Embedder | None = None,
        vector_index: VectorIndex | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._storage = storage
        self._collector = collector
        self._pii = pii
        self._embedder = embedder
        self._vector_index = vector_index

    # -------------------------------------------------------------- entry

    async def discover_source(
        self, source_id: uuid.UUID, *, llm: LeadLlm | None, actor: str
    ) -> DiscoveryStats:
        source = await self._repo.get_source(source_id)
        if source is None or source.competitor_id is not None:
            raise NotFoundError("source", source_id)
        stats = DiscoveryStats(sources=1)
        await self._discover_one(source, llm, stats)
        await self._audit.write(actor, "leads.discovered", "sources", source_id, stats.as_dict())
        return stats

    async def discover_all(self, *, llm: LeadLlm | None, actor: str) -> DiscoveryStats:
        sources = await self._repo.enabled_lead_sources()
        stats = DiscoveryStats(sources=len(sources))
        for source in sources:
            await self._discover_one(source, llm, stats)
        await self._audit.write(actor, "leads.discovered", "sources", None, stats.as_dict())
        return stats

    # ------------------------------------------------------------ pipeline

    async def _discover_one(
        self, source: LeadSourceRow, llm: LeadLlm | None, stats: DiscoveryStats
    ) -> None:
        """One source through the full pipeline. NEVER raises (NFR-1)."""
        now = datetime.now(UTC)
        try:
            docs = await self._collector.collect(source)
        except CollectorNotConfiguredError:
            logger.info("lead_collect_skipped", source_id=str(source.id), reason="no credentials")
            stats.skipped += 1
            await self._repo.set_source_result(source.id, SKIPPED_NO_CREDENTIALS, now)
            return
        except ComplianceRefusedError as exc:
            logger.info("lead_collect_blocked", source_id=str(source.id), reason=exc.reason)
            stats.blocked += 1
            await self._repo.set_source_result(
                source.id, _clip_status("blocked: ", exc.reason), now
            )
            return
        except Exception as exc:  # noqa: BLE001 - per-source isolation
            logger.warning("lead_collect_error", source_id=str(source.id), error=str(exc))
            stats.errors += 1
            await self._repo.set_source_result(source.id, _clip_status("error: ", str(exc)), now)
            return

        try:
            leads_created = await self._process_docs(source, docs, llm, stats, now)
        except Exception as exc:  # noqa: BLE001 - never raise out of a sweep
            logger.exception("lead_pipeline_failed", source_id=str(source.id))
            stats.errors += 1
            await self._repo.set_source_result(source.id, _clip_status("error: ", str(exc)), now)
            return
        await self._repo.set_source_result(
            source.id, f"ok: {len(docs)} docs, {leads_created} leads", now
        )

    async def _process_docs(
        self,
        source: LeadSourceRow,
        docs: list[CollectedDoc],
        llm: LeadLlm | None,
        stats: DiscoveryStats,
        now: datetime,
    ) -> int:
        candidates: list[tuple[uuid.UUID, CollectedDoc]] = []
        for doc in docs:
            stats.docs += 1
            try:
                content_hash = content_sha256(doc.content)
                if await self._repo.raw_document_exists(source.id, content_hash):
                    continue  # seen before: skip silently (dedup §8.1)
                storage_key = f"leads/{source.id}/{content_hash[:16]}.txt"
                await self._storage.put(
                    storage_key, doc.content.encode("utf-8"), "text/plain; charset=utf-8"
                )
                stats.new_docs += 1
                if not is_candidate(doc.content):
                    await self._repo.create_raw_document(
                        source_id=source.id,
                        content_hash=content_hash,
                        storage_key=storage_key,
                        status=RAW_STATUS_NOISE,
                    )
                    stats.noise += 1
                    continue
                raw = await self._repo.create_raw_document(
                    source_id=source.id,
                    content_hash=content_hash,
                    storage_key=storage_key,
                    status=RAW_STATUS_CANDIDATE,
                )
                stats.candidates += 1
                candidates.append((raw.id, doc))
            except Exception as exc:  # noqa: BLE001 - one bad doc never stops the rest
                logger.warning(
                    "lead_doc_failed", source_id=str(source.id), url=doc.url, error=str(exc)
                )
                stats.errors += 1

        verdicts = await self._classify(candidates, llm, stats, now)

        leads_created = 0
        for (raw_id, doc), verdict in zip(candidates, verdicts, strict=True):
            try:
                if not verdict.is_lead:
                    await self._repo.set_raw_document_status(raw_id, RAW_STATUS_NOISE)
                    stats.noise += 1
                    continue
                created = await self._persist(source, doc, verdict, now, stats)
                await self._repo.set_raw_document_status(
                    raw_id, RAW_STATUS_LEAD if created else RAW_STATUS_DUPLICATE
                )
                if created:
                    leads_created += 1
            except Exception as exc:  # noqa: BLE001 - per-document isolation
                logger.warning(
                    "lead_persist_failed", source_id=str(source.id), url=doc.url, error=str(exc)
                )
                stats.errors += 1
        stats.leads += leads_created
        return leads_created

    # ------------------------------------------------------ classify+score

    async def _classify(
        self,
        candidates: list[tuple[uuid.UUID, CollectedDoc]],
        llm: LeadLlm | None,
        stats: DiscoveryStats,
        now: datetime,
    ) -> list[LeadVerdict]:
        verdicts: list[LeadVerdict] = []
        for batch in _chunks(candidates, CLASSIFY_BATCH_SIZE):
            entries: dict[int, dict[str, Any]] | None = None
            if llm is not None:
                entries = await self._classify_batch_llm(batch, llm, stats)
            for index, (_, doc) in enumerate(batch):
                entry = entries.get(index) if entries else None
                if entry is not None:
                    verdicts.append(_verdict_from_llm(entry, doc, now))
                else:
                    verdicts.append(_rules_verdict(doc, now))
        return verdicts

    async def _classify_batch_llm(
        self,
        batch: list[tuple[uuid.UUID, CollectedDoc]],
        llm: LeadLlm,
        stats: DiscoveryStats,
    ) -> dict[int, dict[str, Any]] | None:
        prompt = render_prompt(
            "customer-discovery",
            "classify",
            fallback=CLASSIFY_PROMPT_FALLBACK_TH,
            variables={
                "items": [
                    {"index": index, "text": doc.content[:CLASSIFY_ITEM_MAX_CHARS]}
                    for index, (_, doc) in enumerate(batch)
                ]
            },
        )
        try:
            completion = await llm.complete(
                tier="low", prompt=prompt, max_tokens=CLASSIFY_MAX_TOKENS
            )
        except Exception as exc:  # noqa: BLE001 - AgentLlm contract is never-raise; belt
            logger.warning("lead_classify_llm_failed", error=str(exc))
            return None
        if completion is None:
            return None
        stats.tokens_in += completion.tokens_in
        stats.tokens_out += completion.tokens_out
        stats.cost_usd += completion.cost_usd
        entries = parse_classification_batch(completion.text, len(batch))
        if entries is None:
            logger.warning("lead_classify_unparseable", batch=len(batch))
        return entries

    # -------------------------------------------------------------- persist

    async def _persist(
        self,
        source: LeadSourceRow,
        doc: CollectedDoc,
        verdict: LeadVerdict,
        now: datetime,
        stats: DiscoveryStats,
    ) -> bool:
        """Create the lead (True) or record a re-observation (False)."""
        contact = parse_contact(doc.content, doc.url, source.type)
        dedup = lead_dedup_hash(contact.platform, contact.handle, doc.content)

        existing = await self._repo.find_lead_by_dedup(dedup)
        if existing is None:
            existing = await self._semantic_duplicate(doc.content, now)
        if existing is not None:
            await self._repo.touch_lead(existing.id, now)
            await self._repo.add_lead_event(
                existing.id, "reobserved", {"source": source.name, "url": doc.url}, now
            )
            stats.duplicates += 1
            return False

        contact_json = self._pii.encrypt_contact(
            {"platform": contact.platform, "handle": contact.handle, "url": doc.url}
        )
        lead = await self._repo.create_lead(
            source_id=source.id,
            kind=verdict.kind,
            name=contact.handle,
            contact_json=contact_json,
            locale=verdict.language or None,
            intent_score=verdict.intent_score,
            dedup_hash=dedup,
            first_seen_at=now,
        )
        await self._repo.add_lead_event(
            lead.id,
            "discovered",
            {
                "source": source.name,
                "url": doc.url,
                "excerpt": excerpt(doc.content),
                "suggestion": verdict.suggestion,
            },
            now,
        )
        await self._repo.add_lead_score(
            lead.id,
            model_version=verdict.model_version,
            score=verdict.intent_score,
            features=verdict.features,
            scored_at=now,
        )
        await self._index_lead(lead.id, doc.content, now)
        return True

    # ---------------------------------------------------- semantic dedup

    def _semantic_available(self) -> bool:
        return (
            self._embedder is not None
            and self._embedder.is_available
            and self._vector_index is not None
        )

    async def _semantic_duplicate(self, content: str, now: datetime) -> LeadRow | None:
        """>=0.92-similar lead observed within the last 60 days, else None.

        Degrades to None on any embedding/vector failure (NFR-1) — the exact
        dedup_hash check has already run, so worst case is a duplicate lead,
        never a lost one.
        """
        if not self._semantic_available():
            return None
        assert self._embedder is not None and self._vector_index is not None
        try:
            vector = await self._embedder.embed_query(content)
            hits = await self._vector_index.search(LEADS_COLLECTION, vector, 5)
        except Exception as exc:  # noqa: BLE001 - semantic dedup is best-effort
            logger.warning("lead_semantic_dedup_unavailable", error=str(exc))
            return None
        cutoff = now - timedelta(days=SEMANTIC_WINDOW_DAYS)
        for hit in hits:
            if hit.score < SEMANTIC_DUP_THRESHOLD:
                continue
            lead_id = hit.payload.get("lead_id")
            observed_raw = hit.payload.get("observed_at")
            if not isinstance(lead_id, str) or not isinstance(observed_raw, str):
                continue
            try:
                observed_at = datetime.fromisoformat(observed_raw)
            except ValueError:
                continue
            if observed_at < cutoff:
                continue
            try:
                lead = await self._repo.get_lead(uuid.UUID(lead_id))
            except ValueError:
                continue
            if lead is not None:
                return lead
        return None

    async def _index_lead(self, lead_id: uuid.UUID, content: str, now: datetime) -> None:
        if not self._semantic_available():
            return
        assert self._embedder is not None and self._vector_index is not None
        try:
            vector = await self._embedder.embed_query(content)
            await self._vector_index.upsert(
                LEADS_COLLECTION,
                [
                    VectorPoint(
                        id=str(lead_id),
                        vector=vector,
                        payload={"lead_id": str(lead_id), "observed_at": now.isoformat()},
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001 - indexing is best-effort
            logger.warning("lead_index_failed", lead_id=str(lead_id), error=str(exc))
