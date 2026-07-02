"""M1 renovation: bank_transactions table + inline report bodies.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "bank_transactions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("amount_thb", sa.Numeric(14, 2), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),  # in|out
        sa.Column("bank", sa.Text(), nullable=False),
        sa.Column("account_tail", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'unmatched'"), nullable=False),
        sa.Column(
            "matched_draw_id",
            _UUID,
            sa.ForeignKey("draws.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ambiguous_match", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("dedup_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("dedup_hash", name="uq_bank_transactions_dedup_hash"),
    )
    op.create_index("ix_bank_transactions_status", "bank_transactions", ["status"])
    op.create_index("ix_bank_transactions_occurred_at", "bank_transactions", ["occurred_at"])

    # M1 daily Thai snapshots are stored inline; storage_key remains for MinIO.
    op.add_column("reports", sa.Column("body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "body")
    op.drop_index("ix_bank_transactions_occurred_at", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_status", table_name="bank_transactions")
    op.drop_table("bank_transactions")
