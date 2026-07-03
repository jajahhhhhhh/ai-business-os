"""M2 knowledge base + memory: document pipeline columns, memory consolidation.

documents gains the ingestion-pipeline state (status/error/size_bytes/source);
memories gains consolidated_into (self-FK set on rows merged into a surviving
duplicate). chunks already has the unique (document_id, seq) constraint from
0001 (uq_chunks_document_seq), so nothing to add there.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # pending|parsing|indexed|failed
    op.add_column(
        "documents",
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    )
    op.add_column("documents", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("source", sa.Text(), server_default=sa.text("'upload'"), nullable=False),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.add_column(
        "memories",
        sa.Column(
            "consolidated_into",
            _UUID,
            sa.ForeignKey("memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("memories", "consolidated_into")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_column("documents", "source")
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "error")
    op.drop_column("documents", "status")
