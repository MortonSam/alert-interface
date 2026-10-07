"""pe_snapshots.computation_version: how the P/E was computed (valuation.PE_COMPUTATION_VERSION). Version 2 restates quarters and
closes to the current share basis across recorded splits; rows written before this column exist read as version 1.

Revision ID: a7b8c9d2e4f5
Revises: f6a7b8c9d2e4
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d2e4f5"
down_revision = "f6a7b8c9d2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pe_snapshots", sa.Column("computation_version", sa.SmallInteger(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("pe_snapshots", "computation_version")
