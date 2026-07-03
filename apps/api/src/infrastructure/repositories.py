"""SQLAlchemy implementations of the application repository protocols."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.bank_transactions import MATCHED
from src.application.errors import NotFoundError
from src.application.snapshot import SiteSnapshot
from src.domain.cursor import Cursor
from src.domain.draws import DrawStatus
from src.domain.leads import LeadStage
from src.infrastructure.models import (
    AgentRun,
    BankTransaction,
    ChangeEvent,
    Chunk,
    Competitor,
    Contractor,
    Document,
    Draw,
    Job,
    Lead,
    LeadEvent,
    Memory,
    Milestone,
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


@dataclass(frozen=True, slots=True)
class DrawDisplayData:
    """One draw enriched with quotation/contractor/site context."""

    id: uuid.UUID
    seq: int
    amount_thb: Decimal
    status: str
    requested_at: datetime
    paid_at: datetime | None
    quotation_id: uuid.UUID
    category: str
    contractor_name: str
    site_id: uuid.UUID
    site_name: str


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

    async def list_quotations(self, site_id: uuid.UUID) -> Sequence[Quotation]:
        stmt = (
            sa.select(Quotation)
            .where(Quotation.site_id == site_id, Quotation.deleted_at.is_(None))
            .order_by(Quotation.created_at)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_draws_display(
        self, site_id: uuid.UUID | None, status: str | None
    ) -> Sequence[DrawDisplayData]:
        stmt = (
            sa.select(
                Draw.id,
                Draw.seq,
                Draw.amount_thb,
                Draw.status,
                Draw.requested_at,
                Draw.paid_at,
                Draw.quotation_id,
                Quotation.category,
                Contractor.name.label("contractor_name"),
                Site.id.label("site_id"),
                Site.name.label("site_name"),
            )
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .join(Contractor, Quotation.contractor_id == Contractor.id)
            .join(Site, Quotation.site_id == Site.id)
            .where(Quotation.deleted_at.is_(None))
        )
        if site_id is not None:
            stmt = stmt.where(Quotation.site_id == site_id)
        if status is not None:
            stmt = stmt.where(Draw.status == status)
        stmt = stmt.order_by(Draw.requested_at.desc(), Draw.seq.desc())
        return [
            DrawDisplayData(
                id=row.id,
                seq=row.seq,
                amount_thb=row.amount_thb,
                status=row.status,
                requested_at=row.requested_at,
                paid_at=row.paid_at,
                quotation_id=row.quotation_id,
                category=row.category,
                contractor_name=row.contractor_name,
                site_id=row.site_id,
                site_name=row.site_name,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def list_milestones(self, site_id: uuid.UUID) -> Sequence[Milestone]:
        stmt = (
            sa.select(Milestone)
            .where(Milestone.site_id == site_id)
            .order_by(Milestone.planned_date.asc().nulls_last(), Milestone.created_at)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get_milestone(self, milestone_id: uuid.UUID) -> Milestone | None:
        return await self._session.get(Milestone, milestone_id)

    async def create_milestone(
        self, site_id: uuid.UUID, name: str, planned_date: date | None
    ) -> Milestone:
        return await self._persist(
            Milestone(site_id=site_id, name=name, planned_date=planned_date)
        )

    async def update_milestone(
        self, milestone_id: uuid.UUID, changes: dict[str, Any]
    ) -> Milestone:
        milestone = await self._session.get(Milestone, milestone_id)
        assert milestone is not None  # existence checked by the use case
        for field, value in changes.items():
            setattr(milestone, field, value)
        await self._session.flush()
        await self._session.refresh(milestone)
        return milestone

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


class BankTransactionSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tx_id: uuid.UUID) -> BankTransaction | None:
        return await self._session.get(BankTransaction, tx_id)

    async def get_by_dedup_hash(self, dedup_hash: str) -> BankTransaction | None:
        stmt = sa.select(BankTransaction).where(BankTransaction.dedup_hash == dedup_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        occurred_at: datetime,
        amount_thb: Decimal,
        direction: str,
        bank: str,
        account_tail: str | None,
        raw_text: str,
        source: str,
        status: str,
        matched_draw_id: uuid.UUID | None,
        ambiguous_match: bool,
        dedup_hash: str,
    ) -> BankTransaction:
        transaction = BankTransaction(
            occurred_at=occurred_at,
            amount_thb=amount_thb,
            direction=direction,
            bank=bank,
            account_tail=account_tail,
            raw_text=raw_text,
            source=source,
            status=status,
            matched_draw_id=matched_draw_id,
            ambiguous_match=ambiguous_match,
            dedup_hash=dedup_hash,
        )
        self._session.add(transaction)
        await self._session.flush()
        await self._session.refresh(transaction)
        return transaction

    async def list(self, status: str | None, limit: int) -> Sequence[BankTransaction]:
        stmt = sa.select(BankTransaction)
        if status:
            stmt = stmt.where(BankTransaction.status == status)
        stmt = stmt.order_by(
            BankTransaction.occurred_at.desc(), BankTransaction.created_at.desc()
        ).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def set_match(
        self,
        tx_id: uuid.UUID,
        *,
        status: str,
        matched_draw_id: uuid.UUID | None,
        ambiguous_match: bool,
    ) -> BankTransaction:
        transaction = await self._session.get(BankTransaction, tx_id)
        assert transaction is not None  # existence checked by the use case
        transaction.status = status
        transaction.matched_draw_id = matched_draw_id
        transaction.ambiguous_match = ambiguous_match
        await self._session.flush()
        await self._session.refresh(transaction)
        return transaction

    async def set_status(self, tx_id: uuid.UUID, status: str) -> BankTransaction:
        transaction = await self._session.get(BankTransaction, tx_id)
        assert transaction is not None  # existence checked by the use case
        transaction.status = status
        await self._session.flush()
        await self._session.refresh(transaction)
        return transaction

    async def list_pending_draws(self) -> Sequence[Draw]:
        stmt = (
            sa.select(Draw)
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .where(Draw.status == DrawStatus.PENDING.value, Quotation.deleted_at.is_(None))
            .order_by(Draw.requested_at)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get_draw(self, draw_id: uuid.UUID) -> Draw | None:
        return await self._session.get(Draw, draw_id)


class SnapshotSqlRepository:
    """Aggregations behind the daily Thai snapshot (application/snapshot.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def site_snapshots(self, week_start: datetime, today: date) -> list[SiteSnapshot]:
        zero = sa.literal(Decimal("0"), sa.Numeric(14, 2))

        sites_stmt = sa.select(Site).where(Site.deleted_at.is_(None)).order_by(Site.created_at)
        sites = (await self._session.execute(sites_stmt)).scalars().all()

        pending_stmt = (
            sa.select(
                Quotation.site_id,
                sa.func.count(Draw.id).label("count"),
                sa.func.coalesce(sa.func.sum(Draw.amount_thb), zero).label("total"),
            )
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .where(Draw.status == DrawStatus.PENDING.value, Quotation.deleted_at.is_(None))
            .group_by(Quotation.site_id)
        )
        pending = {
            row.site_id: (row.count, row.total)
            for row in (await self._session.execute(pending_stmt)).all()
        }

        paid_stmt = (
            sa.select(
                Quotation.site_id,
                sa.func.coalesce(sa.func.sum(Draw.amount_thb), zero).label("total"),
            )
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .where(
                Draw.status == DrawStatus.PAID.value,
                Draw.paid_at >= week_start,
                Quotation.deleted_at.is_(None),
            )
            .group_by(Quotation.site_id)
        )
        paid = {
            row.site_id: row.total for row in (await self._session.execute(paid_stmt)).all()
        }

        awaiting_stmt = (
            sa.select(Quotation.site_id, sa.func.count(BankTransaction.id).label("count"))
            .join(Draw, BankTransaction.matched_draw_id == Draw.id)
            .join(Quotation, Draw.quotation_id == Quotation.id)
            .where(BankTransaction.status == MATCHED)
            .group_by(Quotation.site_id)
        )
        awaiting = {
            row.site_id: row.count
            for row in (await self._session.execute(awaiting_stmt)).all()
        }

        overdue_stmt = (
            sa.select(Milestone.site_id, Milestone.name)
            .where(
                Milestone.planned_date.is_not(None),
                Milestone.planned_date < today,
                Milestone.status != "done",
            )
            .order_by(Milestone.planned_date)
        )
        overdue: dict[uuid.UUID, list[str]] = {}
        for row in (await self._session.execute(overdue_stmt)).all():
            overdue.setdefault(row.site_id, []).append(row.name)

        return [
            SiteSnapshot(
                name=site.name,
                pending_draw_count=pending.get(site.id, (0, Decimal("0")))[0],
                pending_draw_total_thb=pending.get(site.id, (0, Decimal("0")))[1],
                paid_this_week_thb=paid.get(site.id, Decimal("0")),
                awaiting_confirmation_count=awaiting.get(site.id, 0),
                overdue_milestones=tuple(overdue.get(site.id, ())),
            )
            for site in sites
        ]

    async def create_report(
        self, *, kind: str, period: str, lang: str, body: str, sent_at: datetime | None
    ) -> Report:
        report = Report(kind=kind, period=period, lang=lang, body=body, sent_at=sent_at)
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)
        return report


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


@dataclass(frozen=True, slots=True)
class ChunkHydrationData:
    """A chunk joined with its document title, for search-result hydration."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    seq: int
    text: str


class KnowledgeBaseSqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_document(
        self,
        *,
        id: uuid.UUID,  # noqa: A002 - mirrors the protocol/column name
        title: str,
        mime: str,
        storage_key: str,
        lang: str | None,
        size_bytes: int,
        source: str,
    ) -> Document:
        document = Document(
            id=id,
            title=title,
            mime=mime,
            storage_key=storage_key,
            lang=lang,
            size_bytes=size_bytes,
            source=source,
            status="pending",
        )
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        stmt = sa.select(Document).where(
            Document.id == document_id, Document.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_documents(self, status: str | None, limit: int) -> Sequence[Document]:
        stmt = sa.select(Document).where(Document.deleted_at.is_(None))
        if status:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def update_document(
        self, document_id: uuid.UUID, changes: dict[str, Any]
    ) -> Document:
        document = await self.get_document(document_id)
        if document is None:
            raise NotFoundError("document", document_id)
        for field, value in changes.items():
            setattr(document, field, value)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def replace_chunks(
        self, document_id: uuid.UUID, chunks: Sequence[tuple[int, str]]
    ) -> Sequence[Chunk]:
        await self._session.execute(sa.delete(Chunk).where(Chunk.document_id == document_id))
        rows = [Chunk(document_id=document_id, seq=seq, text=text) for seq, text in chunks]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    async def set_chunk_point_ids(self, chunk_ids: Sequence[uuid.UUID]) -> None:
        """Record that each chunk's Qdrant point id is its own uuid (as text)."""
        if not chunk_ids:
            return
        await self._session.execute(
            sa.update(Chunk)
            .where(Chunk.id.in_(list(chunk_ids)))
            .values(qdrant_point_id=sa.cast(Chunk.id, sa.Text()))
        )

    async def chunk_count(self, document_id: uuid.UUID) -> int:
        stmt = sa.select(sa.func.count()).select_from(Chunk).where(
            Chunk.document_id == document_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_chunks_with_titles(
        self, chunk_ids: Sequence[uuid.UUID]
    ) -> Sequence[ChunkHydrationData]:
        if not chunk_ids:
            return []
        stmt = (
            sa.select(Chunk.id, Chunk.document_id, Document.title, Chunk.seq, Chunk.text)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(list(chunk_ids)), Document.deleted_at.is_(None))
        )
        return [
            ChunkHydrationData(
                id=row.id,
                document_id=row.document_id,
                document_title=row.title,
                seq=row.seq,
                text=row.text,
            )
            for row in (await self._session.execute(stmt)).all()
        ]


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemorySqlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _active(now: datetime) -> sa.ColumnElement[bool]:
        return sa.and_(
            Memory.consolidated_into.is_(None),
            sa.or_(Memory.expires_at.is_(None), Memory.expires_at > now),
        )

    async def create(
        self,
        *,
        kind: str,
        subject: str,
        body: str,
        importance: int,
        expires_at: datetime | None,
        source_run_id: uuid.UUID | None,
    ) -> Memory:
        memory = Memory(
            kind=kind,
            subject=subject,
            body=body,
            importance=importance,
            expires_at=expires_at,
            source_run_id=source_run_id,
        )
        self._session.add(memory)
        await self._session.flush()
        await self._session.refresh(memory)
        return memory

    async def set_embedding_point(self, memory_id: uuid.UUID, point_id: str) -> Memory:
        memory = await self._session.get(Memory, memory_id)
        if memory is None:
            raise NotFoundError("memory", memory_id)
        memory.embedding_point_id = point_id
        await self._session.flush()
        await self._session.refresh(memory)
        return memory

    async def search_text(
        self, q: str, kind: str | None, limit: int, now: datetime
    ) -> Sequence[Memory]:
        pattern = f"%{_like_escape(q)}%"
        stmt = sa.select(Memory).where(
            self._active(now),
            sa.or_(
                Memory.subject.ilike(pattern, escape="\\"),
                Memory.body.ilike(pattern, escape="\\"),
            ),
        )
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        stmt = stmt.order_by(
            Memory.importance.desc(), Memory.created_at.desc(), Memory.id
        ).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def get_active_many(
        self, memory_ids: Sequence[uuid.UUID], now: datetime
    ) -> Sequence[Memory]:
        if not memory_ids:
            return []
        stmt = sa.select(Memory).where(Memory.id.in_(list(memory_ids)), self._active(now))
        return (await self._session.execute(stmt)).scalars().all()

    async def list_active(self, now: datetime) -> Sequence[Memory]:
        stmt = sa.select(Memory).where(self._active(now)).order_by(Memory.created_at, Memory.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def list_expired(self, now: datetime) -> Sequence[Memory]:
        stmt = sa.select(Memory).where(
            Memory.expires_at.is_not(None), Memory.expires_at <= now
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def mark_consolidated(
        self, memory_ids: Sequence[uuid.UUID], survivor_id: uuid.UUID
    ) -> None:
        if not memory_ids:
            return
        await self._session.execute(
            sa.update(Memory)
            .where(Memory.id.in_(list(memory_ids)))
            .values(consolidated_into=survivor_id)
        )

    async def delete_many(self, memory_ids: Sequence[uuid.UUID]) -> None:
        if not memory_ids:
            return
        await self._session.execute(sa.delete(Memory).where(Memory.id.in_(list(memory_ids))))
