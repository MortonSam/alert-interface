"""Add computation_version to historical_reactions

Revision ID: w6x8y9z0a1b2
Revises: v5w7x8y9z0a1
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "w6x8y9z0a1b2"
down_revision = "v5w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "historical_reactions",
        sa.Column("computation_version", sa.SmallInteger(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("historical_reactions", "computation_version")
