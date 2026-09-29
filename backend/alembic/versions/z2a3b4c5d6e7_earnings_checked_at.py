"""tickers.earnings_checked_at: when the calendar refresh last asked Finnhub about this ticker.

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "z2a3b4c5d6e7"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickers", sa.Column("earnings_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickers", "earnings_checked_at")
