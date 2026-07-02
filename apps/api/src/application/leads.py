"""Lead pipeline use cases: cursor-paginated listing and stage changes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.errors import NotFoundError
from src.application.repositories import AuditWriter, LeadRepository, LeadRow
from src.domain.cursor import Cursor
from src.domain.leads import LeadStage, validate_stage_transition

MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class LeadPage:
    items: list[LeadRow]
    next_cursor: str | None


class LeadUseCases:
    def __init__(self, repo: LeadRepository, audit: AuditWriter) -> None:
        self._repo = repo
        self._audit = audit

    async def list_leads(
        self,
        *,
        stage: LeadStage | None,
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
                stage=stage, min_score=min_score, q=q, after=after, limit=limit + 1
            )
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = Cursor(created_at=last.created_at, id=last.id).encode()
        return LeadPage(items=rows, next_cursor=next_cursor)

    async def change_stage(
        self, lead_id: uuid.UUID, new_stage: LeadStage, actor: str
    ) -> LeadRow:
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
