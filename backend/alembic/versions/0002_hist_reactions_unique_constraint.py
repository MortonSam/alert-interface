"""Add unique constraint on historical_reactions(ticker_id, event_date, event_type)

Revision ID: b3c4d5e6f7a2
Revises: a1b2c3d4e5f6
Create Date: 2026-05-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3c4d5e6f7a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_hist_reaction_ticker_date_type",
        "historical_reactions",
        ["ticker_id", "event_date", "event_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_hist_reaction_ticker_date_type",
        "historical_reactions",
        type_="unique",
    )
