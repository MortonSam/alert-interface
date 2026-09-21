"""NULL pct and price fields on FOMC reactions dated before listing.

SW (Smurfit WestRock, listed 2024-07-08) and TKO (listed 2023-09-12) carry
FOMC reactions computed from a prior entity's prices. Dates are hardcoded
here so the migration stays stable if LISTING_DATE_OVERRIDES changes.

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


PRE_LISTING = (("SW", "2024-07-08"), ("TKO", "2023-09-12"))


def upgrade() -> None:
    conn = op.get_bind()
    for symbol, listed in PRE_LISTING:
        result = conn.execute(sa.text("""
            UPDATE historical_reactions hr
            SET pct_change_1d = NULL,
                pct_change_3d = NULL,
                pct_change_5d = NULL,
                close_before = NULL,
                open_after = NULL,
                close_after = NULL,
                volume_after = NULL
            FROM tickers t
            WHERE t.id = hr.ticker_id
              AND t.symbol = :symbol
              AND hr.event_type = 'fomc'
              AND hr.event_date < CAST(:listed AS date)
              AND (hr.pct_change_1d IS NOT NULL
                   OR hr.pct_change_3d IS NOT NULL
                   OR hr.pct_change_5d IS NOT NULL
                   OR hr.close_before IS NOT NULL)
        """), {"symbol": symbol, "listed": listed})
        print(f"  m9n0o1p2q3r4: {symbol} FOMC rows before {listed} NULLed: {result.rowcount}")


def downgrade() -> None:
    # Data migration — cannot restore original values.
    pass
