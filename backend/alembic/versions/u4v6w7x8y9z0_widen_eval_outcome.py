"""Widen alert_pick_evaluations.outcome from varchar(30) to varchar(40)

Revision ID: u4v6w7x8y9z0
Revises: t3u5v6w7x8y9
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "u4v6w7x8y9z0"
down_revision = "t3u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alert_pick_evaluations", "outcome",
        type_=sa.String(40),
        existing_type=sa.String(30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "alert_pick_evaluations", "outcome",
        type_=sa.String(30),
        existing_type=sa.String(40),
        existing_nullable=False,
    )
