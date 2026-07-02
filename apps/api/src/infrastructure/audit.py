"""Audit-log write helper. Every mutation goes through this."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.models import AuditLog


class SqlAuditWriter:
    """Appends rows to `audit_log` inside the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: uuid.UUID | None,
        diff: dict[str, Any] | None,
    ) -> None:
        self._session.add(
            AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, diff_json=diff)
        )
        await self._session.flush()
