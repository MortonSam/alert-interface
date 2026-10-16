"""ffo_quarters: a REIT's FFO per diluted share for each quarter, read from its earnings release (the Item 2.02 8-K's exhibit) by two
readers that must agree to the cent (services/ffo, the pattern parser and the model with its verbatim quote checked by code), and
cross-checked against the figure computed from XBRL (net income plus depreciation and amortization, less gains on property sales,
over diluted shares) where those tags exist. state: 'ok' (shown), 'held' (the cross-check is more than FFO_GAP_PCT off: the page
says the figure is held), 'unread' (no agreeing reading: the page says it is held because the readings disagree), 'none' (the
release mentions no FFO at all; a REIT keeps EPS until one of its quarters is shown or held). how: the reading's form ("prose statement",
"table row", or "Nareit FFO total over diluted shares" for a release that states FFO only in total, AMT and PLD). One row per symbol and
quarter end.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ffo_quarters",
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("ffo_per_share", sa.Numeric(12, 4), nullable=True),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("quote", sa.Text, nullable=True),
        sa.Column("how", sa.String(40), nullable=True),
        sa.Column("xbrl_ffo_per_share", sa.Numeric(12, 4), nullable=True),
        sa.Column("xbrl_gap_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("accession", sa.String(25), nullable=True),
        sa.Column("exhibit", sa.Text, nullable=True),
        sa.Column("computation_version", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "period_end"),
        sa.CheckConstraint("state IN ('ok', 'held', 'unread', 'none')", name="ffo_quarters_state"),
        sa.CheckConstraint("state IN ('unread', 'none') OR ffo_per_share IS NOT NULL", name="ffo_quarters_figure"),
    )


def downgrade() -> None:
    op.drop_table("ffo_quarters")
