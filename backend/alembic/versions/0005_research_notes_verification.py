"""Add verification columns to research_notes

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("research_notes",
        sa.Column("verification", postgresql.JSONB, nullable=True))
    op.add_column("research_notes",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("research_notes",
        sa.Column("verification_model", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("research_notes", "verification_model")
    op.drop_column("research_notes", "verified_at")
    op.drop_column("research_notes", "verification")
