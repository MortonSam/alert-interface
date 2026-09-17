"""Add report_timing columns to events and historical_reactions, create earnings_report_timing

Track whether earnings were reported before market open (bmo) or after
market close (amc) so reaction windows can be computed correctly.

Revision ID: e1f2g3h4i5j6
Revises: pc01b2c3d4e5
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "e1f2g3h4i5j6"
down_revision = "pc01b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("report_timing", sa.String(10), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "events",
        sa.Column("report_timing_source", sa.String(10), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "historical_reactions",
        sa.Column("report_timing", sa.String(10), nullable=False, server_default="unknown"),
    )

    op.create_table(
        "earnings_report_timing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("timing", sa.String(10), nullable=False, server_default="unknown"),
        sa.Column("source", sa.String(10), nullable=False, server_default="unknown"),
        sa.Column("acceptance_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ert_ticker_date",
        "earnings_report_timing",
        ["ticker_id", "event_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ert_ticker_date", table_name="earnings_report_timing", if_exists=True)
    op.drop_table("earnings_report_timing")
    op.drop_column("historical_reactions", "report_timing")
    op.drop_column("events", "report_timing_source")
    op.drop_column("events", "report_timing")
