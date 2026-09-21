"""Store every option P&L percentage as a percent (-35.0), never a fraction (-0.35).

alert_picks: only the nightly spread-mid close wrote fractions; expiry closes
already wrote percents. A row is converted only when its stored value times 100
matches dollars / cost and the stored value itself does not, so percent rows are
left alone and the migration is safe to re-run.

theses and credit_shadow_picks: every writer stored a fraction, so rows are
converted when value * 100 matches the percent implied by their dollars.

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "p2q3r4s5t6u7"
down_revision = "o1p2q3r4s5t6"
branch_labels = None
depends_on = None

TOL = 0.06  # stored values were rounded to 4 decimals as fractions, 2 as percents

# table, stored pct column, SQL for the percent implied by the row's own dollars
TARGETS = (
    ("alert_picks", "option_pnl_pct",
     "option_pnl_dollars / NULLIF(cost_to_enter, 0)"),
    ("theses", "option_pnl_pct",
     "option_pnl_dollars / NULLIF((entry_premium - COALESCE(entry_premium2, 0)) * contracts, 0)"),
    ("credit_shadow_picks", "pnl_pct",
     "pnl_dollars / NULLIF(max_loss, 0)"),
)


def _convert() -> None:
    conn = op.get_bind()
    for table, col, implied in TARGETS:
        result = conn.execute(sa.text(
            f"UPDATE {table} SET {col} = ROUND({col} * 100, 2) "
            f"WHERE {col} IS NOT NULL AND ({implied}) IS NOT NULL "
            f"AND ABS({col} * 100 - ({implied})) < {TOL} AND ABS({col} - ({implied})) >= {TOL}"
        ))
        total = conn.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {col} IS NOT NULL")).scalar()
        print(f"  p2q3r4s5t6u7: {table}.{col}: {result.rowcount} of {total} rows converted from fraction to percent")


def upgrade() -> None:
    _convert()


def downgrade() -> None:
    # Percent is the correct unit and which rows were fractions is not recorded.
    pass
