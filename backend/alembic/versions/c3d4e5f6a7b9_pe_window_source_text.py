"""pe_snapshots.window_source as text: the label "three XBRL quarters plus the release quarter" is longer than 40 characters.

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pe_snapshots", "window_source", type_=sa.Text(), existing_type=sa.String(40))


def downgrade() -> None:
    op.alter_column("pe_snapshots", "window_source", type_=sa.String(40), existing_type=sa.Text())
