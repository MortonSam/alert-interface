"""A void status for picks made on a wrong report date: kept in the ledger with the reason visible, excluded from the
record's counts and P&L, never deleted, skipped by the closer.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_picks", sa.Column("void_reason", sa.Text(), nullable=True))
    op.add_column("alert_picks", sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_picks", "voided_at")
    op.drop_column("alert_picks", "void_reason")
