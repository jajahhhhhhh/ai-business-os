"""M5 lead discovery: sources gain per-type collector configuration.

sources.config_json carries source-type-specific collector settings for
generic lead sources (competitor_id IS NULL). For reddit sources it is
{"subreddit": "<name>", "query": "<optional keyword filter>"|null}; rss
sources keep using `url` and leave it NULL.

leads / lead_events / lead_scores / raw_documents already match §7 (0001):
leads has contact_json (encrypted at the application layer, §8.5),
cluster_id, dedup_hash, first_seen_at / last_activity_at; nothing else is
needed for this milestone, so the migration stays minimal.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("config_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "config_json")
