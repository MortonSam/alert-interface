"""Shares outstanding on tickers, from the Finnhub profile with its own date: the market value in the Overview is the latest
quote times these shares, both dated in the receipt.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""
from alembic import op
import sqlalchemy as sa

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickers", sa.Column("shares_outstanding", sa.BigInteger(), nullable=True))
    op.add_column("tickers", sa.Column("shares_as_of", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickers", "shares_as_of")
    op.drop_column("tickers", "shares_outstanding")
