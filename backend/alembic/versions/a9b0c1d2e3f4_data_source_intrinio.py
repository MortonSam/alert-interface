"""data_source_enum gets 'intrinio': splits and ex-dividends from Intrinio's price adjustments.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-10-05
"""
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE data_source_enum ADD VALUE IF NOT EXISTS 'intrinio'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values; no-op
    pass
