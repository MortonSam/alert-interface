"""add_rv_min_max

Revision ID: 2ef0b62a3ae6
Revises: 836192e29df5
Create Date: 2026-07-07 20:58:06.089611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2ef0b62a3ae6'
down_revision: Union[str, None] = '836192e29df5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('rv_snapshots', sa.Column('rv_min_1y', sa.Numeric(precision=8, scale=6), nullable=True))
    op.add_column('rv_snapshots', sa.Column('rv_max_1y', sa.Numeric(precision=8, scale=6), nullable=True))


def downgrade() -> None:
    op.drop_column('rv_snapshots', 'rv_max_1y')
    op.drop_column('rv_snapshots', 'rv_min_1y')
