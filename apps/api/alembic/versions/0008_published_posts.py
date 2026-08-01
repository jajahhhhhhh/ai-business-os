"""M6 Postiz publishing: published_posts idempotency ledger.

Records each calendar slot scheduled to Postiz so the weekly rolling publish
never double-posts (dedup_key = date|channel|title). See ADR-0010.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "published_posts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), server_default=sa.text("'postiz'"), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_published_posts_dedup_key"),
    )


def downgrade() -> None:
    op.drop_table("published_posts")
