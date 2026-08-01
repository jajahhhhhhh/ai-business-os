"""Postiz publishing (M6): schedule the content calendar's posts.

Deliberately re-wraps Postiz as a backend REST integration, deviating from
ARCHITECTURE §7 ("third-party MCPs consumed as-is") so the OS can auto-schedule
approved calendar posts with no human in the loop — see ADR-0010. Config-gated
(skips cleanly when Postiz is unconfigured) and idempotent per
(date, channel, title) so the weekly rolling 4-week window never double-posts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

import structlog

from src.application.agents.marketing import dated_slots, post_caption
from src.application.repositories import AuditWriter

logger = structlog.get_logger("application.postiz_publish")


@dataclass(frozen=True, slots=True)
class PostSpec:
    dedup_key: str
    when: date
    channel: str
    caption: str


def build_post_specs(reference: date, titles: list[str], *, today: date) -> list[PostSpec]:
    """Dated, captioned specs for the calendar's slots — future slots only
    (never schedule in the past). dedup_key makes the weekly beat idempotent."""
    specs: list[PostSpec] = []
    for slot in dated_slots(reference, titles):
        if slot.when < today:
            continue
        specs.append(
            PostSpec(
                dedup_key=f"{slot.when.isoformat()}|{slot.channel}|{slot.title}",
                when=slot.when,
                channel=slot.channel,
                caption=post_caption(slot.title),
            )
        )
    return specs


class PostizPublisher(Protocol):
    async def create_post(self, *, integration_id: str, caption: str, when: date) -> str:
        """Create a scheduled Postiz post; returns the created post id."""
        ...


class PublishedPostRepository(Protocol):
    async def exists(self, dedup_key: str) -> bool: ...

    async def record(
        self, *, dedup_key: str, external_id: str, channel: str, scheduled_for: date
    ) -> None: ...


@dataclass
class PublishStats:
    candidates: int = 0
    published: int = 0
    skipped_existing: int = 0
    skipped_no_channel: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class PostizPublishUseCases:
    def __init__(
        self,
        repository: PublishedPostRepository,
        publisher: PostizPublisher,
        audit: AuditWriter,
        *,
        channel_map: dict[str, str],
    ) -> None:
        self._repo = repository
        self._publisher = publisher
        self._audit = audit
        self._channel_map = channel_map

    async def publish(self, specs: list[PostSpec], *, actor: str) -> PublishStats:
        stats = PublishStats(candidates=len(specs))
        for spec in specs:
            integration_id = self._channel_map.get(spec.channel)
            if not integration_id:
                stats.skipped_no_channel += 1  # channel not connected in Postiz
                continue
            if await self._repo.exists(spec.dedup_key):
                stats.skipped_existing += 1  # already scheduled on a prior run
                continue
            try:
                external_id = await self._publisher.create_post(
                    integration_id=integration_id, caption=spec.caption, when=spec.when
                )
            except Exception as exc:  # noqa: BLE001 - one bad post must not abort the batch
                logger.warning("postiz_publish_failed", channel=spec.channel, error=str(exc))
                stats.failed += 1
                continue
            await self._repo.record(
                dedup_key=spec.dedup_key,
                external_id=external_id,
                channel=spec.channel,
                scheduled_for=spec.when,
            )
            stats.published += 1
        if stats.published:
            await self._audit.write(
                actor, "content.published", "published_posts", None, {"count": stats.published}
            )
        logger.info("content_calendar_published", **stats.as_dict())
        return stats
