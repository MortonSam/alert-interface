"""refused_earnings_dates: every duplicate-guard refusal the earnings seeder makes.

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v8w9x0y1z2a3"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refused_earnings_dates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refused_date", sa.Date, nullable=False),
        sa.Column("blocking_row_date", sa.Date, nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="yahoo"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("times_seen", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("ticker_id", "refused_date", "blocking_row_date", name="uq_refused_earnings_dates_pair"),
    )
    op.create_index("ix_refused_earnings_dates_last_seen", "refused_earnings_dates", ["last_seen"])


def downgrade() -> None:
    op.drop_index("ix_refused_earnings_dates_last_seen", table_name="refused_earnings_dates")
    op.drop_table("refused_earnings_dates")
