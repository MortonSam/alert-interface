"""NULL pct values on FOMC reactions before each ticker's first earnings.

Tickers like SW (Smurfit WestRock, listed July 2024) have FOMC
reactions going back to 2021 using price data from the prior entity
that traded under the same symbol. NULLing the pct values renders
them absent without deleting the rows.

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "m9n0o1p2q3r4"
down_revision = "l8m9n0o1p2q3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        WITH first_earnings AS (
            SELECT ticker_id, MIN(event_date) AS first_earn
            FROM historical_reactions
            WHERE event_type = 'earnings'
            GROUP BY ticker_id
        )
        UPDATE historical_reactions hr
        SET pct_change_1d = NULL,
            pct_change_3d = NULL,
            pct_change_5d = NULL,
            close_before = NULL,
            open_after = NULL,
            close_after = NULL,
            volume_after = NULL
        FROM first_earnings fe
        WHERE hr.ticker_id = fe.ticker_id
          AND hr.event_type = 'fomc'
          AND hr.event_date < fe.first_earn
          AND (hr.pct_change_1d IS NOT NULL
               OR hr.pct_change_3d IS NOT NULL
               OR hr.pct_change_5d IS NOT NULL)
    """))


def downgrade() -> None:
    # Data migration — cannot restore original values.
    pass
