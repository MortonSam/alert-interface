"""alert_pick_evaluations.implied_reason: why the implied move is absent on a worksheet row.

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "x0y1z2a3b4c5"
down_revision = "w9x0y1z2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_pick_evaluations", sa.Column("implied_reason", sa.String(120)))


def downgrade() -> None:
    op.drop_column("alert_pick_evaluations", "implied_reason")
