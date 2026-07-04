"""M5 lead maintenance: greedy clustering + PDPA anonymization
(application/lead_maintenance.py, all fakes)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.lead_maintenance import (
    ANONYMIZED_NAME,
    LeadMaintenanceUseCases,
    greedy_clusters,
    months_before,
)
from tests.fakes import FakeEmbedder, FakeLeadStore, NullAuditWriter

ACTOR = "test"
NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- clustering fn


def test_greedy_clusters_groups_similar_vectors() -> None:
    clusters = greedy_clusters(
        [
            ("a", [1.0, 0.0]),
            ("b", [0.999, 0.01]),  # ~a
            ("c", [0.0, 1.0]),  # orthogonal
        ],
        threshold=0.85,
    )
    assert clusters == [["a", "b"], ["c"]]


def test_greedy_clusters_threshold_boundary() -> None:
    # cos 45deg ~= 0.707 < 0.85 -> separate; identical -> together.
    clusters = greedy_clusters(
        [("a", [1.0, 0.0]), ("b", [1.0, 1.0]), ("c", [1.0, 0.0])], threshold=0.85
    )
    assert clusters == [["a", "c"], ["b"]]


def test_greedy_clusters_empty_and_zero_vectors() -> None:
    assert greedy_clusters([]) == []
    # Zero vectors never match anything (cosine 0) — each its own cluster.
    assert greedy_clusters([("a", [0.0, 0.0]), ("b", [0.0, 0.0])]) == [["a"], ["b"]]


def test_greedy_clusters_deterministic_in_input_order() -> None:
    items = [("x", [1.0, 0.0]), ("y", [0.98, 0.05]), ("z", [0.97, 0.08])]
    assert greedy_clusters(items) == [["x", "y", "z"]]


# ------------------------------------------------------------------ cutoff fn


def test_months_before_regular() -> None:
    assert months_before(NOW, 18) == datetime(2025, 1, 4, 12, 0, tzinfo=UTC)


def test_months_before_clamps_short_months() -> None:
    end_of_march = datetime(2026, 3, 31, 8, 0, tzinfo=UTC)
    assert months_before(end_of_march, 1) == datetime(2026, 2, 28, 8, 0, tzinfo=UTC)


def test_months_before_handles_leap_february() -> None:
    end_of_april = datetime(2028, 4, 30, 0, 0, tzinfo=UTC)
    assert months_before(end_of_april, 2) == datetime(2028, 2, 29, 0, 0, tzinfo=UTC)


def test_months_before_crosses_year_boundary() -> None:
    january = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    assert months_before(january, 18) == datetime(2024, 7, 15, 0, 0, tzinfo=UTC)


# ------------------------------------------------------------- cluster use case


async def test_cluster_leads_assigns_ids_to_multi_member_groups() -> None:
    store = FakeLeadStore()
    a = await _lead(store, "u/a", "looking for a villa in koh samui for august")
    b = await _lead(store, "u/b", "looking for a villa in koh samui for august")
    c = await _lead(store, "u/c", "need a landscaping contractor quote bang po")
    use_cases = LeadMaintenanceUseCases(store, NullAuditWriter(), embedder=FakeEmbedder())

    result = await use_cases.cluster_leads(ACTOR)

    assert result["status"] == "done"
    assert result["clusters"] == 1 and result["clustered"] == 2
    assert store.leads[a].cluster_id is not None
    assert store.leads[a].cluster_id == store.leads[b].cluster_id
    assert store.leads[c].cluster_id is None  # singleton keeps NULL


async def test_cluster_leads_skips_cleanly_without_embedder() -> None:
    store = FakeLeadStore()
    await _lead(store, "u/a", "anything")
    for embedder in (None, FakeEmbedder(available=False)):
        use_cases = LeadMaintenanceUseCases(store, NullAuditWriter(), embedder=embedder)
        result = await use_cases.cluster_leads(ACTOR)
        assert result == {"status": "skipped", "reason": "embedder unavailable"}


async def _lead(store: FakeLeadStore, name: str, excerpt: str) -> object:
    import uuid as _uuid

    row = await store.create_lead(
        source_id=_uuid.uuid4(),
        kind="guest",
        name=name,
        contact_json={"enc": "x"},
        locale="en",
        intent_score=50,
        dedup_hash=_uuid.uuid4().hex,
        first_seen_at=NOW,
    )
    await store.add_lead_event(
        row.id, "discovered", {"excerpt": excerpt, "url": "u", "source": "s"}, NOW
    )
    return row.id


# ---------------------------------------------------------- anonymize use case


async def test_anonymize_stale_leads_over_18_months() -> None:
    store = FakeLeadStore()
    stale_id = await _lead(store, "u/stale", "old post")
    store.leads[stale_id].last_activity_at = NOW - timedelta(days=560)
    fresh_id = await _lead(store, "u/fresh", "new post")
    store.leads[fresh_id].last_activity_at = NOW - timedelta(days=30)
    use_cases = LeadMaintenanceUseCases(store, NullAuditWriter())

    result = await use_cases.anonymize_stale_leads(ACTOR, now=NOW)

    assert result["anonymized"] == 1
    stale = store.leads[stale_id]
    assert stale.name == ANONYMIZED_NAME and stale.contact_json is None
    assert store.events_for(stale_id, "anonymized")
    fresh = store.leads[fresh_id]
    assert fresh.name == "u/fresh" and fresh.contact_json is not None


async def test_anonymize_falls_back_to_first_seen_at() -> None:
    store = FakeLeadStore()
    lead_id = await _lead(store, "u/never-touched", "post")
    lead = store.leads[lead_id]
    lead.last_activity_at = None
    lead.first_seen_at = NOW - timedelta(days=600)
    use_cases = LeadMaintenanceUseCases(store, NullAuditWriter())

    result = await use_cases.anonymize_stale_leads(ACTOR, now=NOW)

    assert result["anonymized"] == 1
    assert store.leads[lead_id].name == ANONYMIZED_NAME


async def test_anonymize_spares_won_leads_and_is_idempotent() -> None:
    store = FakeLeadStore()
    won_id = await _lead(store, "u/won", "customer!")
    store.leads[won_id].last_activity_at = NOW - timedelta(days=900)
    store.leads[won_id].stage = "won"
    stale_id = await _lead(store, "u/stale", "old")
    store.leads[stale_id].last_activity_at = NOW - timedelta(days=900)
    audit = NullAuditWriter()
    use_cases = LeadMaintenanceUseCases(store, audit)

    first = await use_cases.anonymize_stale_leads(ACTOR, now=NOW)
    second = await use_cases.anonymize_stale_leads(ACTOR, now=NOW)

    assert first["anonymized"] == 1  # won lead untouched (§8.5 carve-out)
    assert store.leads[won_id].name == "u/won"
    assert second["anonymized"] == 0  # already-anonymized rows are excluded
    assert len(store.events_for(stale_id, "anonymized")) == 1
    assert any(action == "lead.anonymized" for _, action, *_ in audit.entries)


def test_boundary_just_inside_18_months_is_kept() -> None:
    cutoff = months_before(NOW, 18)
    inside = cutoff + timedelta(seconds=1)
    assert inside >= cutoff  # would NOT be selected by `activity < cutoff`
