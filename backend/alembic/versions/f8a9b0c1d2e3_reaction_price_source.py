"""historical_reactions.price_source: which bars a reaction row was computed from.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # null until recompute_reactions_intrinio --write runs; then yfinance | intrinio | stored_history
    op.add_column("historical_reactions", sa.Column("price_source", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("historical_reactions", "price_source")
