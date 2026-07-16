"""add_index_member

Revision ID: b4c2d5e6f8a9
Revises: a3b1c4d5e6f7
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4c2d5e6f8a9'
down_revision: Union[str, None] = 'a3b1c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickers', sa.Column('index_member', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('tickers', 'index_member')
