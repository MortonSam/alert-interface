"""security_records.intrinio_ticker: the ticker Intrinio files the record under, for endpoints that take only a ticker.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("security_records", sa.Column("intrinio_ticker", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("security_records", "intrinio_ticker")
