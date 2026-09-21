"""Ticker timing patterns, and how each timing tag was decided.

ticker_timing_patterns holds each ticker's price-confirmed reporting habit.
earnings_report_timing gains timing_source and timing_rule_version so every
tag records the rule branch and rule version that produced it.

Revision ID: o1p2q3r4s5t6
Revises: n0o1p2q3r4s5
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "o1p2q3r4s5t6"
down_revision = "n0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_timing_patterns",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("pattern", sa.String(10), nullable=False),
        sa.Column("decisive_rows", sa.Integer, nullable=False),
        sa.Column("bmo_share", sa.Numeric(5, 4), nullable=True),
        sa.Column("rule_version", sa.SmallInteger, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("earnings_report_timing", sa.Column("timing_source", sa.String(60), nullable=True))
    op.add_column("earnings_report_timing", sa.Column("timing_rule_version", sa.SmallInteger, nullable=True))


def downgrade() -> None:
    op.drop_column("earnings_report_timing", "timing_rule_version")
    op.drop_column("earnings_report_timing", "timing_source")
    op.drop_table("ticker_timing_patterns")
