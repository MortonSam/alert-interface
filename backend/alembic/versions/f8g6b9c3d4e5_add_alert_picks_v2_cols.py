"""add_alert_picks_v2_cols

Revision ID: f8g6b9c3d4e5
Revises: e7f5a8b9c2d3
Create Date: 2026-07-22 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f8g6b9c3d4e5'
down_revision: Union[str, None] = 'e7f5a8b9c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alert_picks', sa.Column('algo_version', sa.String(20), nullable=False, server_default='v1'))
    op.add_column('alert_picks', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('alert_picks', sa.Column('close_price', sa.Numeric(12, 4), nullable=True))


def downgrade() -> None:
    op.drop_column('alert_picks', 'close_price')
    op.drop_column('alert_picks', 'closed_at')
    op.drop_column('alert_picks', 'algo_version')
