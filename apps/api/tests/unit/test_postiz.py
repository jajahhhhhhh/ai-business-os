"""M6 Postiz publishing: caption/slots, spec building, publish use case, gating."""

from __future__ import annotations

from datetime import date

from src.application.agents.marketing import (
    BRAND_SITE,
    POST_HASHTAGS,
    dated_slots,
    post_caption,
)
from src.application.postiz_publish import (
    PostizPublishUseCases,
    build_post_specs,
)
from src.config import Settings
from src.infrastructure.postiz import PostizClient, build_postiz_publisher

CHANNEL_MAP = {"Instagram": "ig", "Facebook": "fb"}  # Blog deliberately unmapped


# ------------------------------------------------------------- caption + slots


def test_post_caption_strips_planned_suffix_and_is_on_brand() -> None:
    caption = post_caption("Boutique Villa Koh Samui (planned topic)")
    assert "(planned topic)" not in caption
    assert caption.startswith("Boutique Villa Koh Samui —")
    assert BRAND_SITE in caption
    assert POST_HASHTAGS in caption


def test_dated_slots_fill_four_weeks_from_next_monday() -> None:
    slots = dated_slots(date(2026, 7, 20), ["A", "B"])  # 2026-07-20 is a Monday
    assert len(slots) == 12
    assert slots[0].when == date(2026, 7, 27) and slots[0].channel == "Instagram"
    assert all(s.when >= date(2026, 7, 27) for s in slots)


# --------------------------------------------------------------- spec building


def test_build_post_specs_future_only_with_dedup_keys() -> None:
    specs = build_post_specs(date(2026, 7, 20), ["A"], today=date(2026, 7, 20))
    assert len(specs) == 12
    assert specs[0].dedup_key == "2026-07-27|Instagram|A"
    assert specs[0].caption == post_caption("A")


def test_build_post_specs_excludes_past_slots() -> None:
    # Reference in the past → its slots precede `today` → all excluded.
    specs = build_post_specs(date(2026, 7, 1), ["A"], today=date(2026, 8, 1))
    assert specs == []


# ----------------------------------------------------------------- use case


class FakePublisher:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, date]] = []

    async def create_post(self, *, integration_id: str, caption: str, when: date) -> str:
        if self.fail:
            raise RuntimeError("postiz down")
        self.calls.append((integration_id, when))
        return f"post-{integration_id}-{when.isoformat()}"


class FakePubRepo:
    def __init__(self, existing: tuple[str, ...] = ()) -> None:
        self.existing = set(existing)
        self.recorded: list[str] = []

    async def exists(self, dedup_key: str) -> bool:
        return dedup_key in self.existing

    async def record(self, *, dedup_key, external_id, channel, scheduled_for) -> None:  # noqa: ANN001
        self.recorded.append(dedup_key)
        self.existing.add(dedup_key)


class FakeAudit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def write(self, actor, action, entity, entity_id, diff) -> None:  # noqa: ANN001
        self.actions.append(action)


def _specs() -> list:
    # 2 titles over 12 slots → Instagram×4, Facebook×4 (mapped), Blog×4 (unmapped).
    return build_post_specs(date(2026, 7, 20), ["A", "B"], today=date(2026, 7, 20))


async def test_publish_schedules_mapped_channels_and_records() -> None:
    repo, publisher, audit = FakePubRepo(), FakePublisher(), FakeAudit()
    uc = PostizPublishUseCases(repo, publisher, audit, channel_map=CHANNEL_MAP)
    stats = await uc.publish(_specs(), actor="worker")

    assert stats.candidates == 12
    assert stats.published == 8  # Instagram + Facebook slots
    assert stats.skipped_no_channel == 4  # Blog unmapped
    assert len(repo.recorded) == 8 and len(publisher.calls) == 8
    assert audit.actions == ["content.published"]


async def test_publish_is_idempotent_on_existing_dedup_keys() -> None:
    specs = _specs()
    already = specs[0].dedup_key  # first Instagram slot already published
    repo = FakePubRepo(existing=(already,))
    uc = PostizPublishUseCases(repo, FakePublisher(), FakeAudit(), channel_map=CHANNEL_MAP)
    stats = await uc.publish(specs, actor="worker")

    assert stats.skipped_existing == 1
    assert stats.published == 7


async def test_publish_failure_does_not_record_or_audit() -> None:
    repo, audit = FakePubRepo(), FakeAudit()
    uc = PostizPublishUseCases(repo, FakePublisher(fail=True), audit, channel_map=CHANNEL_MAP)
    stats = await uc.publish(_specs(), actor="worker")

    assert stats.published == 0 and stats.failed == 8
    assert repo.recorded == [] and audit.actions == []


# -------------------------------------------------------------------- gating


def test_build_postiz_publisher_gated_by_config() -> None:
    assert build_postiz_publisher(Settings()) is None
    assert build_postiz_publisher(Settings(postiz_api_url="https://p.local")) is None  # no key
    assert isinstance(
        build_postiz_publisher(Settings(postiz_api_url="https://p.local", postiz_api_key="k")),
        PostizClient,
    )
