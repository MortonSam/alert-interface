"""Split historical_reactions unique constraint for analyst actions

The old constraint (ticker_id, event_date, event_type) assumed one reaction per
ticker per date per type.  Analyst actions can have multiple events on the same
date (different firms), so we replace it with:

- A partial unique index on (ticker_id, event_date, event_type) WHERE
  event_type = 'earnings'  — preserves the one-per-date invariant for earnings.
- A partial unique index on (event_id) WHERE event_id IS NOT NULL — guarantees
  one reaction per event row (covers analyst actions and any future event-linked
  types).

Revision ID: x7y9z0a1b2c3
Revises: w6x8y9z0a1b2
Create Date: 2026-09-16
"""
from alembic import op

revision = "x7y9z0a1b2c3"
down_revision = "w6x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_hist_reaction_ticker_date_type", "historical_reactions", type_="unique")

    op.execute(
        "CREATE UNIQUE INDEX uq_hist_reaction_ticker_date_earnings "
        "ON historical_reactions (ticker_id, event_date, event_type) "
        "WHERE event_type = 'earnings'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_hist_reaction_ticker_event "
        "ON historical_reactions (ticker_id, event_id) "
        "WHERE event_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_hist_reaction_ticker_event")
    op.execute("DROP INDEX IF EXISTS uq_hist_reaction_ticker_date_earnings")
    op.create_unique_constraint(
        "uq_hist_reaction_ticker_date_type",
        "historical_reactions",
        ["ticker_id", "event_date", "event_type"],
    )
