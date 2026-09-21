"""Stamp remaining v1 earnings reactions as v3 with NULL pct fields.

68 rows stayed at computation_version=1 after the v3 cutover:
  - 46 rows: event_date fell outside the 5-year lookback window
  - 22 rows: event_date within lookback but yfinance no longer serves
    those dates, so seed_historical_reactions never encounters them

The v1 pct values were computed with non-timing-aware windows and do not
match v3 semantics. Null them so they render absent (CLAUDE.md rule) and
stamp computation_version=3 to clear the mixed-versions banner.

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "i5j6k7l8m9n0"
down_revision = "h4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("""
            UPDATE historical_reactions
            SET pct_change_1d = NULL,
                pct_change_3d = NULL,
                pct_change_5d = NULL,
                computation_version = 3
            WHERE event_type = 'earnings'
              AND computation_version < 3
        """)
    )


def downgrade() -> None:
    # Data migration — cannot restore original v1 pct values.
    pass
