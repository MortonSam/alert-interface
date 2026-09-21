"""Add partial unique index for FOMC reactions

The split_hist_reaction_unique migration replaced the blanket
(ticker_id, event_date, event_type) constraint with a partial unique
index scoped to earnings.  FOMC reactions were left without a unique
index, so every upsert ON CONFLICT fails with "constraint does not
exist".

Adds a matching partial unique index for FOMC.

Revision ID: g3h4i5j6k7l8
Revises: f2g3h4i5j6k7
Create Date: 2026-09-21
"""
from alembic import op

revision = "g3h4i5j6k7l8"
down_revision = "f2g3h4i5j6k7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_hist_reaction_ticker_date_fomc "
        "ON historical_reactions (ticker_id, event_date, event_type) "
        "WHERE event_type = 'fomc'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_hist_reaction_ticker_date_fomc")
