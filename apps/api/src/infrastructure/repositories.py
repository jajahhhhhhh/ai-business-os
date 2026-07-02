"""SQLAlchemy implementations of the application repository protocols."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.cursor import Cursor
from src.domain.draws import DrawStatus
from src.domain.leads import LeadStage
from src.infrastructure.models import (
    AgentRun,
    ChangeEvent,
    Competitor,
    Contractor,
    Draw,
    Job,
    Lead,
    LeadEvent,
    Quotation,
    Report,
    Site,
)


@dataclass(frozen=True, slots=True)
class SpendRowData:
    site_id: uuid.UUID
    category: str
    quoted_thb: Decimal
    paid_thb: Decimal
    pending_thb: Decimal


class RenovationSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _persist[T](self, instance: T) -> T:
        self._session.add(instance)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def create_site(
        self, name: str, location: str | None, budget_thb: Decimal | None
    ) -> Site:
        return await self._persist(Site(name=name, location=location, budget_thb=budget_thb))

    async def list_sites(self) -> Sequence[Site]:
        stmt = sa.select(Site).where(Site.deleted_at.is_(None)).order_by(Site.created_at)
        return (await self._session.execute(stmt)).scalars().all()

    async def get_site(self, site_id: uuid.UUID) -> Site | None:
        stmt = sa.select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_contractor(
        self, name: str, contact: str | None, line_id: str | None
    ) -> Contractor:
        return await self._persist(Contractor(name=name, contact=contact, line_id=line_id))

    async def get_contractor(self, contractor_id: uuid.UUID) -> Contractor | None:
        stmt = sa.select(Contractor).where(
            Contractor.id == contractor_id, Contractor.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_quotation(
        self,
        site_id: uuid.UUID,
        contractor_id: uuid.UUID,
        category: str,
        amount_thb: Decimal,
        status: str,
    ) -> Quotation:
        return await self._persist(
            Quotation(
                site_id=site_id,
                contractor_id=contractor_id,
                category=category,
                amount_thb=amount_thb,
                status=status,
            )
        )

    async def get_quotation(self, quotation_id: uuid.UUID) -> Quotation | None:
        stmt = sa.select(Quotation).where(
            Quotation.id == quotation_id, Quotation.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_draws(self, quotation_id: uuid.UUID) -> Sequence[Draw]:
        stmt = sa.select(Draw).where(Draw.quotation_id == quotation_id).order_by(Draw.seq)
        return (await self._session.execute(stmt)).scalars().all()

    async def create_draw(
        self, quotation_id: uuid.UUID, seq: int, amount_thb: Decimal
    ) -> Draw:
        return await self._persist(
            Draw(quotation_id=quotation_id, seq=seq, amount_thb=amount_thb)
        )

    async def get_draw(self, draw_id: uuid.UUID) -> Draw | None:
        return await self._session.get(Draw, draw_id)

    async def mark_draw_paid(self, draw_id: uuid.UUID, paid_at: datetime) -> Draw:
        draw = await self._session.get(Draw, draw_id)
        assert draw is not None  # existence checked by the use case
        draw.status = DrawStatus.PAID.value
        draw.paid_at = paid_at
        await self._session.flush()
        await self._session.refresh(draw)
        return draw

    async def spend_rows(self) -> Sequence[SpendRowData]:
        zero = sa.literal(Decimal("0"), sa.Numeric(14, 2))

        quoted_stmt = (
            sa.select(
                Quotation.site_id,
                Quotation.category,
                sa.func.coalesce(sa.func.sum(Quotation.amount_thb), zero).label("quoted"),
            )
            .where(Quotation.deleted_at.is_(None))
            .group_by(Quotation.site_id, Quotation.category)
        )
        draws_stmt = (
            sa.select(
                Quotation.site_id,
                Quotation.category,
                sa.func.coalesce(
                    sa.func.sum(
                        sa.case(
                            (Draw.status == DrawStatus.PAID.value, Draw.amount_thb), else_=zero
                        )
                    ),
                    zero,
                ).label("paid"),
                sa.func.coalesce(
                    sa.func.sum(
                        sa.case(
                            (Draw.status == DrawStatus.PENDING.value, Draw.amount_thb), else_=zero
                        )
                    ),
                    zero,
                ).label("pending"),
            )
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .where(Quotation.deleted_at.is_(None))
            .group_by(Quotation.site_id, Quotation.category)
        )

        merged: dict[tuple[uuid.UUID, str], dict[str, Decimal]] = {}
        for site_id, category, quoted in (await self._session.execute(quoted_stmt)).all():
            merged[(site_id, category)] = {
                "quoted": quoted,
                "paid": Decimal("0"),
                "pending": Decimal("0"),
            }
        for site_id, category, paid, pending in (await self._session.execute(draws_stmt)).all():
            entry = merged.setdefault(
                (site_id, category),
                {"quoted": Decimal("0"), "paid": Decimal("0"), "pending": Decimal("0")},
            )
            entry["paid"] = paid
            entry["pending"] = pending

        return [
            SpendRowData(
                site_id=site_id,
                category=category,
                quoted_thb=values["quoted"],
                paid_thb=values["paid"],
                pending_thb=values["pending"],
            )
            for (site_id, category), values in merged.items()
        ]


class LeadSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, lead_id: uuid.UUID) -> Lead | None:
        stmt = sa.select(Lead).where(Lead.id == lead_id, Lead.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_page(
        self,
        *,
        stage: LeadStage | None,
        min_score: int | None,
        q: str | None,
        after: Cursor | None,
        limit: int,
    ) -> Sequence[Lead]:
        stmt = sa.select(Lead).where(Lead.deleted_at.is_(None))
        if stage is not None:
            stmt = stmt.where(Lead.stage == stage.value)
        if min_score is not None:
            stmt = stmt.where(Lead.intent_score >= min_score)
        if q:
            stmt = stmt.where(Lead.name.ilike(f"%{q}%"))
        if after is not None:
            stmt = stmt.where(
                sa.tuple_(Lead.created_at, Lead.id) < sa.tuple_(after.created_at, after.id)
            )
        stmt = stmt.order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def set_stage(
        self, lead_id: uuid.UUID, stage: LeadStage, activity_at: datetime
    ) -> Lead:
        lead = await self._session.get(Lead, lead_id)
        assert lead is not None  # existence checked by the use case
        lead.stage = stage.value
        lead.last_activity_at = activity_at
        await self._session.flush()
        await self._session.refresh(lead)
        return lead

    async def add_event(
        self,
        lead_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any] | None,
        occurred_at: datetime,
    ) -> None:
        self._session.add(
            LeadEvent(
                lead_id=lead_id, type=event_type, payload_json=payload, occurred_at=occurred_at
            )
        )
        await self._session.flush()


class CompetitorSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[Competitor]:
        stmt = (
            sa.select(Competitor)
            .where(Competitor.deleted_at.is_(None))
            .order_by(Competitor.name)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, competitor_id: uuid.UUID) -> Competitor | None:
        stmt = sa.select(Competitor).where(
            Competitor.id == competitor_id, Competitor.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        name: str,
        kind: str | None,
        website: str | None,
        listing_urls: dict[str, Any] | None,
    ) -> Competitor:
        competitor = Competitor(
            name=name, kind=kind, website=website, listing_urls_json=listing_urls
        )
        self._session.add(competitor)
        await self._session.flush()
        await self._session.refresh(competitor)
        return competitor

    async def changes_since(
        self, competitor_id: uuid.UUID, since: datetime | None
    ) -> Sequence[ChangeEvent]:
        stmt = sa.select(ChangeEvent).where(ChangeEvent.competitor_id == competitor_id)
        if since is not None:
            stmt = stmt.where(ChangeEvent.detected_at >= since)
        stmt = stmt.order_by(ChangeEvent.detected_at.desc())
        return (await self._session.execute(stmt)).scalars().all()


class AgentSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_runs(
        self, agent: str | None, status: str | None, limit: int
    ) -> Sequence[AgentRun]:
        stmt = sa.select(AgentRun)
        if agent:
            stmt = stmt.where(AgentRun.agent == agent)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def list_reports(self, kind: str | None, limit: int) -> Sequence[Report]:
        stmt = sa.select(Report)
        if kind:
            stmt = stmt.where(Report.kind == kind)
        stmt = stmt.order_by(Report.created_at.desc()).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()


class JobSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[Job]:
        stmt = sa.select(Job).order_by(Job.name)
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def mark_run_requested(self, job_id: uuid.UUID, at: datetime) -> Job:
        job = await self._session.get(Job, job_id)
        assert job is not None  # existence checked by the router
        job.last_run_at = at
        job.last_status = "queued"
        await self._session.flush()
        await self._session.refresh(job)
        return job
