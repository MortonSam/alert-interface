"""Add option_pnl columns to alert_picks.

Revision ID: l4m2h9i0j1k2
Revises: k3l1g8h9i0j1
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "l4m2h9i0j1k2"
down_revision = "k3l1g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_picks", sa.Column("option_pnl_dollars", sa.Numeric(12, 2), nullable=True))
    op.add_column("alert_picks", sa.Column("option_pnl_pct", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_picks", "option_pnl_pct")
    op.drop_column("alert_picks", "option_pnl_dollars")
