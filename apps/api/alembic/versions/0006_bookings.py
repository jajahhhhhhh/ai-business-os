"""M7 operations: PMS bookings for occupancy/pricing analytics.

A `bookings` table holding reservations ingested from a PMS (Smoobu/Lodgify).
No guest PII — dates, amount, status and channel only. Idempotent per
(provider, external_id) so repeated syncs update in place.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'booked'"), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.Text(), server_default=sa.text("'THB'"), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("property_ref", sa.Text(), nullable=True),
        sa.Column("guests", sa.Integer(), nullable=True),
        sa.Column(
            "site_id", _UUID, sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("provider", "external_id", name="uq_bookings_provider_external"),
    )
    op.create_index("ix_bookings_check_in", "bookings", ["check_in"])
    op.create_index("ix_bookings_status", "bookings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_check_in", table_name="bookings")
    op.drop_table("bookings")
