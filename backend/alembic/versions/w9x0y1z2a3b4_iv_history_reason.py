"""iv_history.atm_iv_reason: why a snapshot wrote no ATM IV.

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "w9x0y1z2a3b4"
down_revision = "v8w9x0y1z2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("iv_history", sa.Column("atm_iv_reason", sa.String(160)))


def downgrade() -> None:
    op.drop_column("iv_history", "atm_iv_reason")
