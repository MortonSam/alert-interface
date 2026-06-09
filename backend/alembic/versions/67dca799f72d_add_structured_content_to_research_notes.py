"""add_structured_content_to_research_notes

Revision ID: 67dca799f72d
Revises: 1d881432f6e3
Create Date: 2026-06-09 23:10:26.779096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '67dca799f72d'
down_revision: Union[str, None] = '1d881432f6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("research_notes", sa.Column("structured_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("research_notes", "structured_content")
