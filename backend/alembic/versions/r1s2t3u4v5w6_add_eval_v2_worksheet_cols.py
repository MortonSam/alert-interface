"""Add v2 worksheet columns to alert_pick_evaluations.

Revision ID: r1s2t3u4v5w6
Revises: q9r7m4n5o6p7
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "r1s2t3u4v5w6"
down_revision = "q9r7m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_pick_evaluations", sa.Column("momentum_20d", sa.Numeric(8, 2), nullable=True))
    op.add_column("alert_pick_evaluations", sa.Column("prior_n", sa.Integer(), nullable=True))
    op.add_column("alert_pick_evaluations", sa.Column("expected_move_pct", sa.Numeric(8, 2), nullable=True))
    op.add_column("alert_pick_evaluations", sa.Column("implied_move_pct", sa.Numeric(8, 2), nullable=True))
    op.add_column("alert_pick_evaluations", sa.Column("verdict", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alert_pick_evaluations", "verdict")
    op.drop_column("alert_pick_evaluations", "implied_move_pct")
    op.drop_column("alert_pick_evaluations", "expected_move_pct")
    op.drop_column("alert_pick_evaluations", "prior_n")
    op.drop_column("alert_pick_evaluations", "momentum_20d")
