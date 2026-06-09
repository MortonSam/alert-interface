"""add_status_to_research_notes

Revision ID: 1d881432f6e3
Revises: 077dea957eda
Create Date: 2026-06-09 22:17:36.902051

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1d881432f6e3'
down_revision: Union[str, None] = '077dea957eda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("research_notes", sa.Column("status", sa.Text(), nullable=False, server_default="complete"))
    op.add_column("research_notes", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_notes", "error")
    op.drop_column("research_notes", "status")
