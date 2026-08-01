"""M7 guest comms: bookings.review_requested_at for post-checkout nudges.

Set once the review request has been sent so a booking is nudged at most once.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "review_requested_at")
