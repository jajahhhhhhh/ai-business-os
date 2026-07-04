"""Lead pipeline use cases: cursor-paginated listing, detail and stage changes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.errors import NotFoundError
from src.application.repositories import (
    AuditWriter,
    LeadEventRow,
    LeadRepository,
    LeadRow,
    LeadScoreRow,
)
from src.domain.cursor import Cursor
from src.domain.leads import LeadStage, validate_stage_transition

MAX_PAGE_SIZE = 200
DETAIL_EVENT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class LeadPage:
    items: list[LeadRow]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class LeadDetail:
    """GET /v1/leads/{id} payload: lead + events + latest score + suggestion.

    `suggestion` is the Thai follow-up one-liner recorded on the newest
    'discovered' event by the customer-discovery agent (M5)."""

    lead: LeadRow
    events: Sequence[LeadEventRow]
    score: LeadScoreRow | None
    suggestion: str | None


class LeadUseCases:
    def __init__(self, repo: LeadRepository, audit: AuditWriter) -> None:
        self._repo = repo
        self._audit = audit

    async def list_leads(
        self,
        *,
        stage: LeadStage | None,
        kind: str | None = None,
        min_score: int | None,
        q: str | None,
        cursor: str | None,
        limit: int,
    ) -> LeadPage:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        after = Cursor.decode(cursor) if cursor else None
        # Fetch one extra row to learn whether another page exists.
        rows = list(
            await self._repo.list_page(
                stage=stage, kind=kind, min_score=min_score, q=q, after=after, limit=limit + 1
            )
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = Cursor(created_at=last.created_at, id=last.id).encode()
        return LeadPage(items=rows, next_cursor=next_cursor)

    async def get_detail(self, lead_id: uuid.UUID) -> LeadDetail:
        lead = await self._repo.get(lead_id)
        if lead is None:
            raise NotFoundError("lead", lead_id)
        events = await self._repo.list_events(lead_id, DETAIL_EVENT_LIMIT)
        score = await self._repo.latest_score(lead_id)
        suggestion: str | None = None
        for event in events:  # newest first: the freshest discovery suggestion wins
            if event.type == "discovered":
                payload = event.payload_json or {}
                value = payload.get("suggestion")
                if isinstance(value, str) and value.strip():
                    suggestion = value
                break
        return LeadDetail(lead=lead, events=events, score=score, suggestion=suggestion)

    async def change_stage(self, lead_id: uuid.UUID, new_stage: LeadStage, actor: str) -> LeadRow:
        lead = await self._repo.get(lead_id)
        if lead is None:
            raise NotFoundError("lead", lead_id)
        current = LeadStage(lead.stage)
        validate_stage_transition(current, new_stage)
        now = datetime.now(UTC)
        updated = await self._repo.set_stage(lead_id, new_stage, now)
        await self._repo.add_event(
            lead_id,
            "stage_changed",
            {"from": current.value, "to": new_stage.value},
            now,
        )
        await self._audit.write(
            actor,
            "lead.stage_changed",
            "leads",
            lead_id,
            {"stage": {"from": current.value, "to": new_stage.value}},
        )
        return updated
