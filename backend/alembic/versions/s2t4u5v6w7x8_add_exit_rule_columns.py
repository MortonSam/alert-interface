"""Add exit_rule, exit_date, stock_move_5d to alert_picks

Revision ID: s2t4u5v6w7x8
Revises: r1s2t3u4v5w6
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "s2t4u5v6w7x8"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_picks", sa.Column("exit_rule", sa.String(40), nullable=True))
    op.add_column("alert_picks", sa.Column("exit_date", sa.Date(), nullable=True))
    op.add_column("alert_picks", sa.Column("stock_move_5d", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_picks", "stock_move_5d")
    op.drop_column("alert_picks", "exit_date")
    op.drop_column("alert_picks", "exit_rule")
