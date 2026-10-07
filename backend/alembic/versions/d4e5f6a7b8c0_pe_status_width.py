"""pe_snapshots.status widened for "not_meaningful_yet" (a corporate action inside the four-quarter window).

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c0"
down_revision = "c3d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pe_snapshots", "status", type_=sa.String(24), existing_type=sa.String(16))


def downgrade() -> None:
    op.alter_column("pe_snapshots", "status", type_=sa.String(16), existing_type=sa.String(24))
