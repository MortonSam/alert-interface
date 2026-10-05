"""Block C: ticker inactivity reasons and aliases, Intrinio's active flag on records, and when a reaction's prices were computed.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickers", sa.Column("inactive_reason", sa.Text(), nullable=True))      # why is_active is false, in words
    op.add_column("tickers", sa.Column("inactive_since", sa.Date(), nullable=True))       # the date the reason names
    op.add_column("security_records", sa.Column("intrinio_active", sa.Boolean(), nullable=True))   # Intrinio's active flag at the last refresh
    op.add_column("historical_reactions", sa.Column("price_computed_at", sa.DateTime(timezone=True), nullable=True))  # when the prices and moves were last written
    op.create_table(
        "ticker_aliases",
        sa.Column("old_symbol", sa.String(10), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("renamed_on", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ticker_aliases")
    op.drop_column("historical_reactions", "price_computed_at")
    op.drop_column("security_records", "intrinio_active")
    op.drop_column("tickers", "inactive_since")
    op.drop_column("tickers", "inactive_reason")
