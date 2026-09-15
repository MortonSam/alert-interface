"""Widen shadow_picks.v2_decision from varchar(30) to varchar(80)

Revision ID: t3u5v6w7x8y9
Revises: s2t4u5v6w7x8
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "t3u5v6w7x8y9"
down_revision = "s2t4u5v6w7x8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "shadow_picks", "v2_decision",
        type_=sa.String(80),
        existing_type=sa.String(30),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "shadow_picks", "v2_decision",
        type_=sa.String(30),
        existing_type=sa.String(80),
        existing_nullable=True,
    )
