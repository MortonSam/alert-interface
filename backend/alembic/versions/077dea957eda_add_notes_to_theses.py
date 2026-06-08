"""add_notes_to_theses

Revision ID: 077dea957eda
Revises: c2d3e4f5a6b7
Create Date: 2026-06-08 18:36:27.048406

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '077dea957eda'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('theses', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('theses', 'notes')
