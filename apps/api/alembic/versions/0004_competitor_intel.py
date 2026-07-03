"""M3 competitor intelligence: sources gain competitor linkage + sweep state.

sources.competitor_id ties a monitored source to a competitor (nullable —
generic lead sources have no competitor). last_fetched_at / last_status record
the most recent sweep outcome per source ('ok'|'unchanged'|'changed'|
'refused'|'error'). snapshots and change_events already exist (0001);
competitors needs no changes (listing_urls_json, active, soft delete exist).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "competitor_id",
            _UUID,
            sa.ForeignKey("competitors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sources", sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True)
    )
    # ok|unchanged|changed|refused|error
    op.add_column("sources", sa.Column("last_status", sa.Text(), nullable=True))
    op.create_index("ix_sources_competitor_id", "sources", ["competitor_id"])


def downgrade() -> None:
    op.drop_index("ix_sources_competitor_id", table_name="sources")
    op.drop_column("sources", "last_status")
    op.drop_column("sources", "last_fetched_at")
    op.drop_column("sources", "competitor_id")
