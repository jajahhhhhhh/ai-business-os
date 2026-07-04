"""M5 lead discovery: source validation, LLM batch parsing, pipeline flows
and dedup decisions (application/lead_discovery.py, all fakes)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.application.errors import ComplianceRefusedError, LeadSourceInvalidError
from src.application.lead_discovery import (
    LEADS_COLLECTION,
    MODEL_VERSION_LLM,
    MODEL_VERSION_RULES,
    SKIPPED_NO_CREDENTIALS,
    CollectedDoc,
    DiscoveryStats,
    LeadDiscoveryUseCases,
    LeadSourceUseCases,
    normalize_subreddit,
    parse_classification_batch,
    validate_lead_source,
)
from src.application.ports import VectorPoint
from src.infrastructure.pii import PiiCipher
from tests.fakes import (
    FakeAgentLlm,
    FakeEmbedder,
    FakeLeadCollector,
    FakeLeadStore,
    InMemoryObjectStorage,
    InMemoryVectorIndex,
    NullAuditWriter,
)

ACTOR = "test"

TH_LEAD = (
    "u/somchai_75\nหาวิลล่าที่เกาะสมุย\n\n" "กำลังตามหาวิลล่าแถวสมุยสำหรับ 4 คน เดือนหน้า งบ 30,000 บาทครับ"
)
EN_LEAD = (
    "u/jane_doe\nLooking for a pool villa in Koh Samui\n\n"
    "We are looking for a villa in Koh Samui in August for 2 people, budget $1500."
)
NOISE = "u/bob\nBest ramen in Bangkok\n\nWhere do I find good ramen around Sukhumvit?"


def _doc(content: str, url: str = "https://www.reddit.com/r/kohsamui/1") -> CollectedDoc:
    return CollectedDoc(url=url, content=content, fetched_at=datetime.now(UTC))


def _build(
    *,
    embedder: FakeEmbedder | None = None,
    vector_index: InMemoryVectorIndex | None = None,
) -> tuple[LeadDiscoveryUseCases, FakeLeadStore, FakeLeadCollector, InMemoryObjectStorage]:
    store = FakeLeadStore()
    collector = FakeLeadCollector()
    storage = InMemoryObjectStorage()
    use_cases = LeadDiscoveryUseCases(
        store,
        NullAuditWriter(),
        storage=storage,
        collector=collector,
        pii=PiiCipher("unit-test-key"),
        embedder=embedder,
        vector_index=vector_index,
    )
    return use_cases, store, collector, storage


# ------------------------------------------------------------ source validation


def test_rss_source_requires_url() -> None:
    with pytest.raises(LeadSourceInvalidError):
        validate_lead_source("rss", None, None)


def test_rss_source_blocklisted_url_refused() -> None:
    with pytest.raises(ComplianceRefusedError):
        validate_lead_source("rss", "https://www.facebook.com/groups/samui", None)


def test_rss_source_valid_url_passes_through() -> None:
    url, config = validate_lead_source("rss", "https://blog.example.com/feed.xml", None)
    assert url == "https://blog.example.com/feed.xml"
    assert config is None


def test_reddit_source_requires_subreddit() -> None:
    with pytest.raises(LeadSourceInvalidError):
        validate_lead_source("reddit", None, None)
    with pytest.raises(LeadSourceInvalidError):
        validate_lead_source("reddit", None, {"query": "villa"})


def test_reddit_subreddit_normalized() -> None:
    _, config = validate_lead_source("reddit", None, {"subreddit": "r/KohSamui/"})
    assert config == {"subreddit": "kohsamui", "query": None}


@pytest.mark.parametrize("raw", ["r/KohSamui", "/r/KohSamui/", "KOHSAMUI"])
def test_normalize_subreddit_variants(raw: str) -> None:
    assert normalize_subreddit(raw) == "kohsamui"


def test_normalize_subreddit_rejects_garbage() -> None:
    for bad in ("", "   ", "a b c", "r/", "no!chars"):
        with pytest.raises(LeadSourceInvalidError):
            normalize_subreddit(bad)


def test_unknown_source_type_refused() -> None:
    with pytest.raises(LeadSourceInvalidError):
        validate_lead_source("website", "https://example.com", None)


async def test_registry_update_rechecks_blocklist_on_url_change() -> None:
    store = FakeLeadStore()
    use_cases = LeadSourceUseCases(store, NullAuditWriter())
    source = await use_cases.create_source(
        name="Samui blog",
        type="rss",
        url="https://blog.example.com/feed.xml",
        config=None,
        rate_limit_per_hr=12,
        actor=ACTOR,
    )
    with pytest.raises(ComplianceRefusedError):
        await use_cases.update_source(source.id, {"url": "https://facebook.com/feed"}, ACTOR)


# ---------------------------------------------------------- LLM batch parsing

VALID_BATCH = (
    '[{"index": 0, "is_lead": true, "kind": "guest", "intent_score": 80,'
    ' "language": "en", "suggestion": "ตอบกลับแนะนำวิลล่า"},'
    ' {"index": 1, "is_lead": false, "kind": "guest", "intent_score": 5,'
    ' "language": "en", "suggestion": null}]'
)


def test_parse_batch_valid_json() -> None:
    entries = parse_classification_batch(VALID_BATCH, 2)
    assert entries is not None and set(entries) == {0, 1}
    assert entries[0]["kind"] == "guest"


def test_parse_batch_fenced_json() -> None:
    fenced = f"```json\n{VALID_BATCH}\n```"
    entries = parse_classification_batch(fenced, 2)
    assert entries is not None and set(entries) == {0, 1}


def test_parse_batch_with_surrounding_prose() -> None:
    text = f"นี่คือผลการวิเคราะห์:\n{VALID_BATCH}\nจบรายงาน"
    entries = parse_classification_batch(text, 2)
    assert entries is not None and set(entries) == {0, 1}


def test_parse_batch_malformed_returns_none() -> None:
    assert parse_classification_batch("ไม่มี JSON ที่ใช้ได้", 2) is None
    assert parse_classification_batch('{"index": 0}', 2) is None  # not an array
    assert parse_classification_batch("[{broken", 2) is None


def test_parse_batch_drops_bad_indexes() -> None:
    text = (
        '[{"index": 0, "is_lead": true}, {"index": 9, "is_lead": true},'
        ' {"index": "x"}, "not-a-dict", {"index": 0, "is_lead": false}]'
    )
    entries = parse_classification_batch(text, 2)
    assert entries is not None
    assert set(entries) == {0}
    assert entries[0]["is_lead"] is True  # first occurrence wins


# ------------------------------------------------------------- pipeline flows


async def test_discover_rules_fallback_creates_scored_leads() -> None:
    use_cases, store, collector, storage = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(TH_LEAD), _doc(EN_LEAD), _doc(NOISE)])

    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.docs == 3 and stats.candidates == 2
    assert stats.leads == 2 and stats.noise == 1 and stats.errors == 0
    assert source.last_status == "ok: 3 docs, 2 leads"
    assert source.last_checked_at is not None
    assert len(store.leads) == 2
    for lead in store.leads.values():
        assert lead.stage == "discovered"
        assert lead.name.startswith("u/")
        assert set(lead.contact_json) == {"enc"}  # encrypted at rest
        assert store.events_for(lead.id, "discovered")
    assert {score.model_version for score in store.lead_scores} == {MODEL_VERSION_RULES}
    # Raw docs persisted with statuses; content stored for audit.
    statuses = sorted(raw.status for raw in store.raw_documents.values())
    assert statuses == ["lead", "lead", "noise"]
    assert len(storage.objects) == 3


async def test_discover_decrypts_back_to_original_contact() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(EN_LEAD, url="https://www.reddit.com/r/kohsamui/9")])
    await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    (lead,) = store.leads.values()
    contact = PiiCipher("unit-test-key").decrypt_contact(lead.contact_json)
    assert contact == {
        "platform": "reddit",
        "handle": "u/jane_doe",
        "url": "https://www.reddit.com/r/kohsamui/9",
    }


async def test_discover_llm_path_records_llm_verdicts() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(TH_LEAD), _doc(EN_LEAD)])
    llm = FakeAgentLlm(
        '[{"index": 0, "is_lead": true, "kind": "guest", "intent_score": 88,'
        ' "language": "th", "suggestion": "ตอบภาษาไทยพร้อมลิงก์วิลล่า"},'
        ' {"index": 1, "is_lead": false, "kind": "guest", "intent_score": 10,'
        ' "language": "en", "suggestion": null}]'
    )

    stats = await use_cases.discover_source(source.id, llm=llm, actor=ACTOR)

    assert stats.leads == 1 and stats.noise == 1
    assert stats.tokens_in == 100 and stats.tokens_out == 50
    (lead,) = store.leads.values()
    assert lead.intent_score == 88 and lead.locale == "th"
    (score,) = store.lead_scores
    assert score.model_version == MODEL_VERSION_LLM
    (event,) = store.events_for(lead.id, "discovered")
    assert event.payload_json["suggestion"] == "ตอบภาษาไทยพร้อมลิงก์วิลล่า"
    # Prompt carried both items, batched in one call.
    assert len(llm.calls) == 1
    assert "[0]" in llm.calls[0]["prompt"] and "[1]" in llm.calls[0]["prompt"]


async def test_discover_llm_malformed_falls_back_to_rules() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(EN_LEAD)])
    llm = FakeAgentLlm("ขออภัย ไม่สามารถตอบเป็น JSON ได้")

    stats = await use_cases.discover_source(source.id, llm=llm, actor=ACTOR)

    assert stats.leads == 1
    (score,) = store.lead_scores
    assert score.model_version == MODEL_VERSION_RULES
    # LLM usage is still booked even when the reply is unusable.
    assert stats.tokens_in == 100


async def test_discover_batches_at_most_10_per_llm_call() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    docs = [
        _doc(f"u/user{i}\nvilla samui please {i}", url=f"https://reddit.com/{i}") for i in range(12)
    ]
    collector.set(source.id, docs)
    llm = FakeAgentLlm(None, None)  # both batches fall back to rules

    await use_cases.discover_source(source.id, llm=llm, actor=ACTOR)

    assert len(llm.calls) == 2  # 10 + 2


async def test_recollect_skips_seen_raw_documents() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(TH_LEAD), _doc(EN_LEAD), _doc(NOISE)])
    await use_cases.discover_source(source.id, llm=None, actor=ACTOR)
    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.new_docs == 0 and stats.leads == 0 and stats.duplicates == 0
    assert len(store.leads) == 2 and len(store.raw_documents) == 3
    assert source.last_status == "ok: 3 docs, 0 leads"


async def test_exact_dedup_reobserves_same_handle_same_text() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(EN_LEAD)])
    await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    # Same author + same normalized text, different raw bytes (case/spacing).
    variant = EN_LEAD.upper().replace(" ", "  ")
    normalized_variant = variant.lower()
    assert normalized_variant != EN_LEAD  # raw content differs -> new raw doc
    collector.set(source.id, [_doc(variant.lower())])
    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.duplicates == 1 and stats.leads == 0
    (lead,) = store.leads.values()
    assert store.events_for(lead.id, "reobserved")
    assert lead.last_activity_at is not None


async def test_semantic_dedup_reobserves_within_window() -> None:
    embedder = FakeEmbedder()
    index = InMemoryVectorIndex()
    use_cases, store, collector, _ = _build(embedder=embedder, vector_index=index)
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})

    collector.set(source.id, [_doc(EN_LEAD)])
    await use_cases.discover_source(source.id, llm=None, actor=ACTOR)
    (original,) = list(store.leads.values())

    # Different author (so the exact hash differs) posting identical text:
    # trigram vectors are identical -> similarity 1.0 >= 0.92.
    same_text_other_author = EN_LEAD.replace("u/jane_doe", "u/jane_alt")
    collector.set(source.id, [_doc(same_text_other_author)])
    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.duplicates == 1 and stats.leads == 0
    assert len(store.leads) == 1
    assert store.events_for(original.id, "reobserved")


async def test_semantic_dedup_ignores_stale_observations() -> None:
    embedder = FakeEmbedder()
    index = InMemoryVectorIndex()
    use_cases, store, collector, _ = _build(embedder=embedder, vector_index=index)
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})

    # Seed an identical-text point observed 61 days ago for an existing lead.
    old_lead = await store.create_lead(
        source_id=source.id,
        kind="guest",
        name="u/old",
        contact_json=None,
        locale="en",
        intent_score=10,
        dedup_hash="other-hash",
        first_seen_at=datetime.now(UTC) - timedelta(days=90),
    )
    stale = (datetime.now(UTC) - timedelta(days=61)).isoformat()
    vector = await embedder.embed_query(EN_LEAD)
    await index.upsert(
        LEADS_COLLECTION,
        [
            VectorPoint(
                id=str(old_lead.id),
                vector=vector,
                payload={"lead_id": str(old_lead.id), "observed_at": stale},
            )
        ],
    )

    collector.set(source.id, [_doc(EN_LEAD)])
    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.leads == 1 and stats.duplicates == 0  # window expired -> new lead
    assert len(store.leads) == 2


async def test_semantic_dedup_skipped_without_embedder() -> None:
    use_cases, store, collector, _ = _build(embedder=FakeEmbedder(available=False))
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.set(source.id, [_doc(EN_LEAD)])
    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)
    assert stats.leads == 1  # pipeline works; only the semantic check is skipped


# ------------------------------------------------- per-source status + isolation


async def test_collector_not_configured_records_skipped() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("r/kohsamui", "reddit", config={"subreddit": "kohsamui"})
    collector.not_configured.add(source.id)

    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.skipped == 1 and stats.errors == 0
    assert source.last_status == SKIPPED_NO_CREDENTIALS


async def test_compliance_refusal_records_blocked() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("blog", "rss", url="https://blog.example.com/feed.xml")
    collector.set(source.id, ComplianceRefusedError("robots_txt", "disallowed"))

    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.blocked == 1
    assert source.last_status is not None and source.last_status.startswith("blocked: ")


async def test_fetch_error_records_error_status() -> None:
    use_cases, store, collector, _ = _build()
    source = store.add_source("blog", "rss", url="https://blog.example.com/feed.xml")
    collector.set(source.id, ConnectionError("boom"))

    stats = await use_cases.discover_source(source.id, llm=None, actor=ACTOR)

    assert stats.errors == 1
    assert source.last_status is not None and source.last_status.startswith("error: ")


async def test_discover_all_isolates_source_failures() -> None:
    use_cases, store, collector, _ = _build()
    bad = store.add_source("bad", "rss", url="https://bad.example.com/feed.xml")
    good = store.add_source("good", "reddit", config={"subreddit": "kohsamui"})
    disabled = store.add_source("off", "rss", url="https://off.example.com/f.xml", enabled=False)
    collector.set(bad.id, RuntimeError("exploded"))
    collector.set(good.id, [_doc(EN_LEAD)])

    stats = await use_cases.discover_all(llm=None, actor=ACTOR)

    assert stats.sources == 2  # the disabled source is not swept
    assert stats.errors == 1 and stats.leads == 1
    assert bad.last_status.startswith("error: ")
    assert good.last_status == "ok: 1 docs, 1 leads"
    assert disabled.last_status is None
    assert disabled.id not in collector.calls


async def test_discover_source_competitor_owned_is_not_found() -> None:
    from src.application.errors import NotFoundError

    use_cases, store, collector, _ = _build()
    source = store.add_source(
        "villa:website", "rss", url="https://x.example.com/f.xml", competitor_id=uuid.uuid4()
    )
    with pytest.raises(NotFoundError):
        await use_cases.discover_source(source.id, llm=None, actor=ACTOR)


# ------------------------------------------------------ registry wiring checks


def test_trigger_and_jobs_registries_include_customer_discovery() -> None:
    from src.interfaces.routers.agents import TRIGGERS
    from src.interfaces.routers.jobs import DISPATCHABLE

    assert TRIGGERS["customer-discovery"] == ("customer-discovery", "discover-all")
    assert DISPATCHABLE["collect_all_lead_sources"] == (
        "src.worker.collect_all_lead_sources",
        (),
    )
    assert DISPATCHABLE["cluster_leads"] == ("src.worker.cluster_leads", ())
    assert DISPATCHABLE["anonymize_stale_leads"] == ("src.worker.anonymize_stale_leads", ())


def test_customer_discovery_budget_default() -> None:
    from decimal import Decimal

    from src.config import _default_agent_budgets

    assert _default_agent_budgets()["customer-discovery"] == Decimal("0.50")


def test_discovery_stats_as_dict_is_json_safe() -> None:
    import json

    stats = DiscoveryStats(sources=1)
    json.dumps(stats.as_dict())  # cost_usd serialized as str
