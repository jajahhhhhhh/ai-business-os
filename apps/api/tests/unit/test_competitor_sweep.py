"""M3 sweep state machine + §8.4 registration compliance (unit, all fakes)."""

from __future__ import annotations

import uuid

import pytest

from src.application.competitor_intel import (
    CompetitorIntelUseCases,
    check_url_compliance,
)
from src.application.errors import ComplianceRefusedError, NotFoundError
from src.application.ports import ChangeClassification
from tests.fakes import (
    FakeChangeAnalyst,
    FakeCompetitorIntelRepository,
    FakeFetcher,
    InMemoryObjectStorage,
    NullAuditWriter,
)

ACTOR = "test"
URL = "https://example-villa.com"
HTML_V1 = "<h1>Sunset Villa</h1><p>Pool villa in Lipa Noi</p>"
HTML_V2 = "<h1>Sunset Villa</h1><p>Pool villa in Lipa Noi</p><p>ราคาใหม่ 4,900 บาท</p>"


Built = tuple[
    CompetitorIntelUseCases, FakeCompetitorIntelRepository, FakeFetcher, InMemoryObjectStorage
]


def _build(analyst: FakeChangeAnalyst | None = None) -> Built:
    repo = FakeCompetitorIntelRepository()
    fetcher = FakeFetcher()
    storage = InMemoryObjectStorage()
    use_cases = CompetitorIntelUseCases(
        repo,
        NullAuditWriter(),
        storage=storage,
        fetcher=fetcher,
        analyst=analyst or FakeChangeAnalyst(None),
    )
    return use_cases, repo, fetcher, storage


async def _add_source(
    repo: FakeCompetitorIntelRepository,
    competitor_id: uuid.UUID,
    url: str = URL,
    type_: str = "website",
):
    return await repo.create_source(
        name=f"c:{type_}",
        type=type_,
        url=url,
        competitor_id=competitor_id,
        rate_limit_per_hr=6,
        tos_policy="allowed",
        robots_ok=True,
        enabled=True,
    )


# ------------------------------------------------------------- state machine


async def test_first_sweep_stores_baseline_without_change_event() -> None:
    use_cases, repo, fetcher, storage = _build()
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["baseline"] == 1 and stats["changed"] == 0
    assert repo.change_events == []  # deliberately NO event for the baseline
    assert len(repo.snapshots) == 1
    key = repo.snapshots[0].storage_key
    assert key.startswith(f"snapshots/{competitor.id}/{source.id}/")
    assert b"Sunset Villa" in storage.objects[key][0]
    assert repo.sources[source.id].last_status == "baseline"
    assert repo.sources[source.id].last_checked_at is not None


async def test_unchanged_content_writes_no_new_snapshot() -> None:
    use_cases, repo, fetcher, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)

    await use_cases.sweep_competitor(competitor.id, ACTOR)
    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["unchanged"] == 1
    assert len(repo.snapshots) == 1
    assert repo.change_events == []
    assert repo.sources[source.id].last_status == "unchanged"


async def test_changed_content_creates_event_via_fallback_classifier() -> None:
    use_cases, repo, fetcher, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)
    await use_cases.sweep_competitor(competitor.id, ACTOR)

    fetcher.set(URL, HTML_V2)
    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["changed"] == 1
    assert len(repo.snapshots) == 2
    [event] = repo.change_events
    assert (event.category, event.severity) == ("pricing", "high")
    assert "ราคาใหม่ 4,900 บาท" in event.summary
    assert event.snapshot_id == repo.snapshots[-1].id
    assert repo.sources[source.id].last_status == "changed"


async def test_analyst_receives_diff_and_its_verdict_wins() -> None:
    analyst = FakeChangeAnalyst(
        ChangeClassification(category="promotion", severity="critical", summary="ลดแรงมาก")
    )
    use_cases, repo, fetcher, _ = _build(analyst)
    competitor = repo.add_competitor("Sunset Villa")
    await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)
    await use_cases.sweep_competitor(competitor.id, ACTOR)
    fetcher.set(URL, HTML_V2)

    await use_cases.sweep_competitor(competitor.id, ACTOR)

    [(diff, name)] = analyst.classify_calls
    assert name == "Sunset Villa"
    assert "+ราคาใหม่ 4,900 บาท" in diff  # unified diff of the normalized text
    [event] = repo.change_events
    assert (event.category, event.severity, event.summary) == (
        "promotion",
        "critical",
        "ลดแรงมาก",
    )


async def test_baseline_never_calls_the_analyst() -> None:
    analyst = FakeChangeAnalyst(ChangeClassification(category="other", severity="low", summary="x"))
    use_cases, repo, fetcher, _ = _build(analyst)
    competitor = repo.add_competitor("Sunset Villa")
    await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)

    await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert analyst.classify_calls == []


async def test_compliance_refusal_marks_blocked_and_continues() -> None:
    use_cases, repo, fetcher, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    blocked = await _add_source(repo, competitor.id, url="https://blocked.example.com")
    ok = await _add_source(repo, competitor.id, url=URL)
    fetcher.set("https://blocked.example.com", ComplianceRefusedError("robots_txt", "disallowed"))
    fetcher.set(URL, HTML_V1)

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["blocked"] == 1 and stats["baseline"] == 1
    assert repo.sources[blocked.id].last_status == "blocked: robots_txt"
    assert repo.sources[ok.id].last_status == "baseline"  # sweep continued
    assert len(repo.snapshots) == 1  # nothing stored for the blocked source


async def test_fetch_error_records_truncated_error_status() -> None:
    use_cases, repo, fetcher, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id)
    fetcher.set(URL, ConnectionError("boom " + "x" * 300))

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["errors"] == 1
    status = repo.sources[source.id].last_status
    assert status is not None and status.startswith("error: boom")
    assert len(status) <= len("error: ") + 120
    assert repo.snapshots == [] and repo.change_events == []


async def test_rss_source_snapshots_parsed_items_not_raw_xml() -> None:
    use_cases, repo, fetcher, storage = _build()
    competitor = repo.add_competitor("Sunset Villa")
    await _add_source(repo, competitor.id, url="https://example.com/feed", type_="rss")
    fetcher.set(
        "https://example.com/feed",
        "<rss><channel><item><title>โปรใหม่</title>"
        "<description>ลด 20%</description></item></channel></rss>",
    )

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["baseline"] == 1
    text = storage.objects[repo.snapshots[0].storage_key][0].decode("utf-8")
    assert text == "โปรใหม่ — ลด 20%"


async def test_malformed_rss_is_a_per_source_error() -> None:
    use_cases, repo, fetcher, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id, url="https://example.com/feed", type_="rss")
    fetcher.set("https://example.com/feed", "this is not xml at all")

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)

    assert stats["errors"] == 1
    assert repo.sources[source.id].last_status.startswith("error: ")


async def test_disabled_sources_and_inactive_competitors_are_skipped() -> None:
    use_cases, repo, fetcher, _ = _build()
    active = repo.add_competitor("Active Villa")
    inactive = repo.add_competitor("Sleeping Villa", active=False)
    disabled = await _add_source(repo, active.id, url="https://a.example.com")
    disabled.enabled = False
    await _add_source(repo, inactive.id, url="https://b.example.com")

    stats = await use_cases.sweep_all(ACTOR)

    assert stats["sources"] == 0
    assert fetcher.calls == []


async def test_storage_failure_never_escapes_the_sweep() -> None:
    class BrokenStorage(InMemoryObjectStorage):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            raise ConnectionError("minio is down")

    repo = FakeCompetitorIntelRepository()
    fetcher = FakeFetcher()
    use_cases = CompetitorIntelUseCases(
        repo,
        NullAuditWriter(),
        storage=BrokenStorage(),
        fetcher=fetcher,
        analyst=FakeChangeAnalyst(None),
    )
    competitor = repo.add_competitor("Sunset Villa")
    source = await _add_source(repo, competitor.id)
    fetcher.set(URL, HTML_V1)

    stats = await use_cases.sweep_competitor(competitor.id, ACTOR)  # must not raise

    assert stats["errors"] == 1
    assert repo.sources[source.id].last_status.startswith("error: ")


async def test_sweeping_unknown_competitor_raises_not_found() -> None:
    use_cases, _, _, _ = _build()
    with pytest.raises(NotFoundError):
        await use_cases.sweep_competitor(uuid.uuid4(), ACTOR)


# ---------------------------------------------------------- §8.4 registration


@pytest.mark.parametrize(
    "url",
    [
        "https://facebook.com/somevilla",
        "https://www.facebook.com/somevilla",
        "https://m.facebook.com/somevilla",
        "https://fb.com/x",
        "https://instagram.com/villa",
        "https://www.airbnb.com/rooms/1",
        "https://airbnb.co.th/rooms/1",
        "https://www.booking.com/hotel/th/villa.html",
        "https://agoda.com/villa",
    ],
)
def test_blocklisted_urls_are_refused_with_thai_84_detail(url: str) -> None:
    with pytest.raises(ComplianceRefusedError) as exc_info:
        check_url_compliance(url)
    assert exc_info.value.reason == "hard_blocklist"
    assert "§8.4" in str(exc_info.value)


def test_lookalike_domains_are_not_blocked() -> None:
    check_url_compliance("https://notfacebook.com/page")  # suffix match only
    check_url_compliance("https://example-villa.com")


def test_non_http_urls_are_refused() -> None:
    with pytest.raises(ComplianceRefusedError) as exc_info:
        check_url_compliance("ftp://example.com/feed")
    assert exc_info.value.reason == "invalid_url"


async def test_register_competitor_refuses_facebook_source_atomically() -> None:
    use_cases, repo, _, _ = _build()
    with pytest.raises(ComplianceRefusedError):
        await use_cases.register_competitor(
            name="Copycat Villa",
            kind="villa",
            website=None,
            listing_urls=None,
            sources=[("website", "https://facebook.com/copycat")],
            actor=ACTOR,
        )
    assert repo.competitors == {} and repo.sources == {}  # nothing was written


async def test_register_competitor_auto_creates_website_source() -> None:
    use_cases, repo, _, _ = _build()
    result = await use_cases.register_competitor(
        name="Sunset Villa",
        kind="villa",
        website=URL,
        listing_urls=None,
        sources=[],
        actor=ACTOR,
    )
    [source] = result.sources
    assert (source.type, source.url) == ("website", URL)
    assert source.name == "Sunset Villa:website"
    assert source.tos_policy == "allowed"
    assert source.rate_limit_per_hr == 6
    assert source.enabled is True


async def test_add_source_to_missing_competitor_raises_not_found() -> None:
    use_cases, _, _, _ = _build()
    with pytest.raises(NotFoundError):
        await use_cases.add_source(uuid.uuid4(), type="rss", url=URL, actor=ACTOR)


async def test_remove_source_checks_competitor_ownership() -> None:
    use_cases, repo, _, _ = _build()
    competitor = repo.add_competitor("Sunset Villa")
    other = repo.add_competitor("Other Villa")
    source = await _add_source(repo, competitor.id)
    with pytest.raises(NotFoundError):
        await use_cases.remove_source(other.id, source.id, ACTOR)
    await use_cases.remove_source(competitor.id, source.id, ACTOR)
    assert repo.sources == {}
