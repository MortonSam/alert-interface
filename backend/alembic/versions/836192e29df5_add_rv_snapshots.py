"""add_rv_snapshots

Revision ID: 836192e29df5
Revises: 67dca799f72d
Create Date: 2026-07-07 20:36:16.783201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '836192e29df5'
down_revision: Union[str, None] = '67dca799f72d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rv_snapshots',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('symbol', sa.String(length=10), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('rv_20d', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('rv_rank', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('rv_percentile', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('sample_days', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'as_of_date', name='uq_rv_snapshot_symbol_date')
    )
    op.create_index('ix_rv_snapshot_date_rank', 'rv_snapshots', ['as_of_date', 'rv_rank'], unique=False)
    op.create_index(op.f('ix_rv_snapshots_symbol'), 'rv_snapshots', ['symbol'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rv_snapshots_symbol'), table_name='rv_snapshots')
    op.drop_index('ix_rv_snapshot_date_rank', table_name='rv_snapshots')
    op.drop_table('rv_snapshots')
