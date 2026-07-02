"""Core schema: identity, renovation, leads, competitors, KB, agents, audit.

Revision ID: 0001
Revises:
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", _UUID, primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    ]


def _deleted_at() -> sa.Column:
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    # ------------------------------------------------------------- identity
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'owner'"), nullable=False),
        sa.Column("locale", sa.Text(), server_default=sa.text("'th'"), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "api_keys",
        _id(),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    # ------------------------------------------------------------- collection
    op.create_table(
        "sources",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("tos_policy", sa.Text(), server_default=sa.text("'unreviewed'"), nullable=False),
        sa.Column("robots_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rate_limit_per_hr", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
    )

    # ------------------------------------------------------------- knowledge base
    op.create_table(
        "documents",
        _id(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column("ocr_done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("meili_indexed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("embedded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _deleted_at(),
    )

    # ------------------------------------------------------------- phase A renovation
    op.create_table(
        "sites",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("budget_thb", sa.Numeric(14, 2), nullable=True),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_table(
        "contractors",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contact", sa.Text(), nullable=True),
        sa.Column("line_id", sa.Text(), nullable=True),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_table(
        "quotations",
        _id(),
        sa.Column(
            "site_id", _UUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "contractor_id",
            _UUID,
            sa.ForeignKey("contractors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("amount_thb", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "document_id", _UUID, sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
        ),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_index("ix_quotations_site_id", "quotations", ["site_id"])
    op.create_table(
        "draws",
        _id(),
        sa.Column(
            "quotation_id",
            _UUID,
            sa.ForeignKey("quotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("amount_thb", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evidence_document_id",
            _UUID,
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("quotation_id", "seq", name="uq_draws_quotation_seq"),
    )
    op.create_table(
        "milestones",
        _id(),
        sa.Column(
            "site_id", _UUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("actual_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'planned'"), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_milestones_site_id", "milestones", ["site_id"])

    # ------------------------------------------------------------- leads
    op.create_table(
        "leads",
        _id(),
        sa.Column(
            "source_id", _UUID, sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contact_json", postgresql.JSONB(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("intent_score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stage", sa.Text(), server_default=sa.text("'discovered'"), nullable=False),
        sa.Column("cluster_id", _UUID, nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedup_hash", sa.Text(), nullable=False),
        *_timestamps(),
        _deleted_at(),
        sa.UniqueConstraint("dedup_hash", name="uq_leads_dedup_hash"),
    )
    op.create_index("ix_leads_stage", "leads", ["stage"])
    op.create_index("ix_leads_created_at_id", "leads", ["created_at", "id"])
    op.create_table(
        "lead_events",
        _id(),
        sa.Column(
            "lead_id", _UUID, sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])
    op.create_table(
        "lead_scores",
        _id(),
        sa.Column(
            "lead_id", _UUID, sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("features_json", postgresql.JSONB(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_lead_scores_lead_id", "lead_scores", ["lead_id"])

    # ------------------------------------------------------------- competitors
    op.create_table(
        "competitors",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("listing_urls_json", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_table(
        "snapshots",
        _id(),
        sa.Column(
            "competitor_id",
            _UUID,
            sa.ForeignKey("competitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id", _UUID, sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_snapshots_competitor_captured", "snapshots", ["competitor_id", "captured_at"]
    )
    op.create_table(
        "change_events",
        _id(),
        sa.Column(
            "competitor_id",
            _UUID,
            sa.ForeignKey("competitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id", _UUID, sa.ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), server_default=sa.text("'info'"), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_change_events_competitor_detected", "change_events", ["competitor_id", "detected_at"]
    )

    # ------------------------------------------------------------- raw documents & chunks
    op.create_table(
        "raw_documents",
        _id(),
        sa.Column(
            "source_id", _UUID, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_raw_documents_source_hash"),
    )
    op.create_table(
        "chunks",
        _id(),
        sa.Column(
            "document_id",
            _UUID,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("qdrant_point_id", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("document_id", "seq", name="uq_chunks_document_seq"),
    )

    # ------------------------------------------------------------- agents & automation
    op.create_table(
        "agent_runs",
        _id(),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "parent_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_agent_runs_agent_started", "agent_runs", ["agent", "started_at"])
    op.create_table(
        "memories",
        _id(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("embedding_point_id", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_memories_kind", "memories", ["kind"])
    op.create_table(
        "agent_evals",
        _id(),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_agent_evals_run_id", "agent_evals", ["run_id"])
    op.create_table(
        "jobs",
        _id(),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("cron", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "reports",
        _id(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=True),
        sa.Column("lang", sa.Text(), server_default=sa.text("'th'"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column(
            "generated_by_run_id",
            _UUID,
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_reports_kind", "reports", ["kind"])

    # ------------------------------------------------------------- audit
    op.create_table(
        "audit_log",
        _id(),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("entity_id", _UUID, nullable=True),
        sa.Column("diff_json", postgresql.JSONB(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity", "entity_id"])


def downgrade() -> None:
    # Reverse dependency order; indexes and constraints drop with their tables.
    op.drop_table("audit_log")
    op.drop_table("reports")
    op.drop_table("jobs")
    op.drop_table("agent_evals")
    op.drop_table("memories")
    op.drop_table("agent_runs")
    op.drop_table("chunks")
    op.drop_table("raw_documents")
    op.drop_table("change_events")
    op.drop_table("snapshots")
    op.drop_table("competitors")
    op.drop_table("lead_scores")
    op.drop_table("lead_events")
    op.drop_table("leads")
    op.drop_table("milestones")
    op.drop_table("draws")
    op.drop_table("quotations")
    op.drop_table("contractors")
    op.drop_table("sites")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("api_keys")
    op.drop_table("users")
