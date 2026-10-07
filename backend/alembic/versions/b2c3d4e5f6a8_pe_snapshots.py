"""Trailing P/E storage. eps_quarters: each ticker's quarterly GAAP diluted EPS as parsed from XBRL (the fourth quarter derived
from the 10-K where only the annual figure is filed), refreshed when a newer report may have landed. pe_snapshots: one row per
ticker per price date with the price, the four quarters and their receipts, the window, the P/E or a "not meaningful" status
with its reason, and the five-year history summary. pe_sector_snapshots: the sector median per date with its coverage, shown
only when at least 90% of the sector's active tickers have a fresh window.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eps_quarters",
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("eps", sa.Numeric(12, 4), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("form", sa.String(12), nullable=False),
        sa.Column("derived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "period_end"),
    )
    op.create_table(
        "pe_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),                 # the stored close's date
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),                 # ok | not_meaningful | missing
        sa.Column("reason", sa.Text(), nullable=True),                      # why not meaningful or missing
        sa.Column("trailing_eps", sa.Numeric(12, 4), nullable=True),
        sa.Column("pe", sa.Numeric(10, 2), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("window_source", sa.String(40), nullable=True),           # "XBRL holds the latest reported quarter" | "three XBRL quarters plus the release quarter"
        sa.Column("latest_report", sa.Date(), nullable=True),               # the report the window had to include
        sa.Column("quarters", postgresql.JSONB(), nullable=True),           # [{end, start, eps, source, form, filed, accession?, derived}]
        sa.Column("hist_median", sa.Numeric(10, 2), nullable=True),         # five-year median of our P/E
        sa.Column("hist_share_above", sa.Integer(), nullable=True),         # percent of sessions today's P/E sits above
        sa.Column("hist_sessions", sa.Integer(), nullable=True),
        sa.Column("hist_excluded", sa.Integer(), nullable=True),
        sa.Column("hist_first", sa.Date(), nullable=True),
        sa.Column("hist_last", sa.Date(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "as_of_date", name="uq_pe_snapshots_symbol_date"),
    )
    op.create_index("ix_pe_snapshots_symbol_date", "pe_snapshots", ["symbol", "as_of_date"])
    op.create_table(
        "pe_sector_snapshots",
        sa.Column("sector", sa.String(80), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("median_pe", sa.Numeric(10, 2), nullable=True),
        sa.Column("with_pe", sa.Integer(), nullable=False),                 # tickers with a P/E value
        sa.Column("fresh", sa.Integer(), nullable=False),                   # tickers with a fresh window (a P/E or not meaningful)
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("shown", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("sector", "as_of_date"),
    )


def downgrade() -> None:
    op.drop_table("pe_sector_snapshots")
    op.drop_table("pe_snapshots")
    op.drop_table("eps_quarters")
