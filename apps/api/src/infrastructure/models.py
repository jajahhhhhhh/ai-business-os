"""SQLAlchemy 2.0 models. Must mirror the alembic revision chain (0001-0003) exactly."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
        datetime: sa.DateTime(timezone=True),
        date: sa.Date(),
        Decimal: sa.Numeric(14, 2),
        dict[str, Any]: JSONB(),
        str: sa.Text(),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    # UUIDv4 generated app-side for now; column stays UUID so a move to
    # DB-generated UUIDv7 is a default-swap, not a type migration.
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=sa.func.now(), onupdate=sa.func.now()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


# --------------------------------------------------------------------------- identity


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    role: Mapped[str] = mapped_column(server_default=sa.text("'owner'"))
    locale: Mapped[str] = mapped_column(server_default=sa.text("'th'"))


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]
    hash: Mapped[str] = mapped_column(unique=True)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]")
    )
    expires_at: Mapped[datetime | None]


# --------------------------------------------------------------------------- phase A


class Site(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    location: Mapped[str | None]
    budget_thb: Mapped[Decimal | None]


class Contractor(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "contractors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    contact: Mapped[str | None]
    line_id: Mapped[str | None]


class Quotation(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "quotations"
    __table_args__ = (sa.Index("ix_quotations_site_id", "site_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("sites.id", ondelete="CASCADE"))
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("contractors.id", ondelete="RESTRICT")
    )
    category: Mapped[str]
    amount_thb: Mapped[Decimal]
    status: Mapped[str] = mapped_column(server_default=sa.text("'pending'"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL")
    )


class Draw(TimestampMixin, Base):
    __tablename__ = "draws"
    __table_args__ = (sa.UniqueConstraint("quotation_id", "seq", name="uq_draws_quotation_seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    quotation_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("quotations.id", ondelete="CASCADE")
    )
    seq: Mapped[int]
    amount_thb: Mapped[Decimal]
    status: Mapped[str] = mapped_column(server_default=sa.text("'pending'"))
    requested_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    paid_at: Mapped[datetime | None]
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="SET NULL")
    )


class BankTransaction(TimestampMixin, Base):
    """A bank-alert-sourced account movement (M1 renovation reconciliation)."""

    __tablename__ = "bank_transactions"
    __table_args__ = (
        sa.UniqueConstraint("dedup_hash", name="uq_bank_transactions_dedup_hash"),
        sa.Index("ix_bank_transactions_status", "status"),
        sa.Index("ix_bank_transactions_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    amount_thb: Mapped[Decimal]
    direction: Mapped[str]  # in|out
    bank: Mapped[str]
    account_tail: Mapped[str | None]
    raw_text: Mapped[str]
    source: Mapped[str] = mapped_column(server_default=sa.text("'manual'"))  # manual|gmail
    # unmatched|matched|confirmed|ignored
    status: Mapped[str] = mapped_column(server_default=sa.text("'unmatched'"))
    matched_draw_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("draws.id", ondelete="SET NULL")
    )
    ambiguous_match: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    dedup_hash: Mapped[str]


class Milestone(TimestampMixin, Base):
    __tablename__ = "milestones"
    __table_args__ = (sa.Index("ix_milestones_site_id", "site_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str]
    planned_date: Mapped[date | None]
    actual_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=sa.text("'planned'"))


# --------------------------------------------------------------------------- collection


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (sa.Index("ix_sources_competitor_id", "competitor_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    type: Mapped[str]
    url: Mapped[str | None]
    tos_policy: Mapped[str] = mapped_column(server_default=sa.text("'unreviewed'"))
    robots_ok: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    rate_limit_per_hr: Mapped[int] = mapped_column(server_default=sa.text("60"))
    enabled: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    # M3 competitor intel: source belongs to a competitor (nullable for
    # generic lead sources) + last sweep outcome per source.
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("competitors.id", ondelete="SET NULL")
    )
    last_fetched_at: Mapped[datetime | None]
    # ok|unchanged|changed|refused|error
    last_status: Mapped[str | None]


class RawDocument(TimestampMixin, Base):
    __tablename__ = "raw_documents"
    __table_args__ = (
        sa.UniqueConstraint("source_id", "content_hash", name="uq_raw_documents_source_hash"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("sources.id", ondelete="CASCADE"))
    fetched_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    content_hash: Mapped[str]
    storage_key: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=sa.text("'new'"))


# --------------------------------------------------------------------------- leads


class Lead(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        sa.UniqueConstraint("dedup_hash", name="uq_leads_dedup_hash"),
        sa.Index("ix_leads_stage", "stage"),
        sa.Index("ix_leads_created_at_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("sources.id", ondelete="SET NULL")
    )
    kind: Mapped[str]
    name: Mapped[str]
    contact_json: Mapped[dict[str, Any] | None]
    locale: Mapped[str | None]
    intent_score: Mapped[int] = mapped_column(server_default=sa.text("0"))
    stage: Mapped[str] = mapped_column(server_default=sa.text("'discovered'"))
    cluster_id: Mapped[uuid.UUID | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    last_activity_at: Mapped[datetime | None]
    dedup_hash: Mapped[str]


class LeadEvent(TimestampMixin, Base):
    __tablename__ = "lead_events"
    __table_args__ = (sa.Index("ix_lead_events_lead_id", "lead_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("leads.id", ondelete="CASCADE"))
    type: Mapped[str]
    payload_json: Mapped[dict[str, Any] | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


class LeadScore(TimestampMixin, Base):
    __tablename__ = "lead_scores"
    __table_args__ = (sa.Index("ix_lead_scores_lead_id", "lead_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("leads.id", ondelete="CASCADE"))
    model_version: Mapped[str]
    score: Mapped[int]
    features_json: Mapped[dict[str, Any] | None]
    scored_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


# --------------------------------------------------------------------------- competitors


class Competitor(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "competitors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str]
    kind: Mapped[str | None]
    website: Mapped[str | None]
    listing_urls_json: Mapped[dict[str, Any] | None]
    active: Mapped[bool] = mapped_column(server_default=sa.text("true"))


class Snapshot(TimestampMixin, Base):
    __tablename__ = "snapshots"
    __table_args__ = (sa.Index("ix_snapshots_competitor_captured", "competitor_id", "captured_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("competitors.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("sources.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    content_hash: Mapped[str]
    storage_key: Mapped[str]


class ChangeEvent(TimestampMixin, Base):
    __tablename__ = "change_events"
    __table_args__ = (
        sa.Index("ix_change_events_competitor_detected", "competitor_id", "detected_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("competitors.id", ondelete="CASCADE")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    category: Mapped[str]
    summary: Mapped[str]
    severity: Mapped[str] = mapped_column(server_default=sa.text("'info'"))
    detected_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


# --------------------------------------------------------------------------- knowledge base


class Document(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (sa.Index("ix_documents_status", "status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str]
    mime: Mapped[str]
    storage_key: Mapped[str]
    lang: Mapped[str | None]
    ocr_done: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    meili_indexed: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    embedded: Mapped[bool] = mapped_column(server_default=sa.text("false"))
    # pending|parsing|indexed|failed (M2 ingestion pipeline)
    status: Mapped[str] = mapped_column(server_default=sa.text("'pending'"))
    error: Mapped[str | None]
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger())
    source: Mapped[str] = mapped_column(server_default=sa.text("'upload'"))


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (sa.UniqueConstraint("document_id", "seq", name="uq_chunks_document_seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    seq: Mapped[int]
    text: Mapped[str]
    qdrant_point_id: Mapped[str | None]


# --------------------------------------------------------------------------- agents & automation


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (sa.Index("ix_agent_runs_agent_started", "agent", "started_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent: Mapped[str]
    task_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=sa.text("'queued'"))
    model: Mapped[str | None]
    tokens_in: Mapped[int] = mapped_column(server_default=sa.text("0"))
    tokens_out: Mapped[int] = mapped_column(server_default=sa.text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 4), server_default=sa.text("0"))
    started_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None]
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL")
    )


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (sa.Index("ix_memories_kind", "kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str]
    subject: Mapped[str]
    body: Mapped[str]
    importance: Mapped[int] = mapped_column(server_default=sa.text("3"))
    embedding_point_id: Mapped[str | None]
    expires_at: Mapped[datetime | None]
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    # Set when this memory was merged into a surviving duplicate (M2).
    consolidated_into: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("memories.id", ondelete="SET NULL")
    )


class AgentEval(TimestampMixin, Base):
    __tablename__ = "agent_evals"
    __table_args__ = (sa.Index("ix_agent_evals_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agent_runs.id", ondelete="CASCADE"))
    rubric: Mapped[str]
    score: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2))
    notes: Mapped[str | None]


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)
    cron: Mapped[str]
    enabled: Mapped[bool] = mapped_column(server_default=sa.text("true"))
    last_run_at: Mapped[datetime | None]
    last_status: Mapped[str | None]


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (sa.Index("ix_reports_kind", "kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str]
    period: Mapped[str | None]
    lang: Mapped[str] = mapped_column(server_default=sa.text("'th'"))
    storage_key: Mapped[str | None]
    # M1: short Thai reports are stored inline; larger artifacts use storage_key.
    body: Mapped[str | None]
    generated_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None]


# --------------------------------------------------------------------------- audit


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (sa.Index("ix_audit_log_entity", "entity", "entity_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor: Mapped[str]
    action: Mapped[str]
    entity: Mapped[str]
    entity_id: Mapped[uuid.UUID | None]
    diff_json: Mapped[dict[str, Any] | None]
    at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
