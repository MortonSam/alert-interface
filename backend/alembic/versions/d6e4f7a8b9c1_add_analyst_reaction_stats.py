"""add_analyst_reaction_stats

Revision ID: d6e4f7a8b9c1
Revises: c5d3e6f7a8b0
Create Date: 2026-07-20 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd6e4f7a8b9c1'
down_revision: Union[str, None] = 'c5d3e6f7a8b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analyst_reaction_stats',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(10), nullable=False),
        sa.Column('upgrade_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_1d_upgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('median_1d_upgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('avg_5d_upgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('upgrade_5d_continuation_pct', sa.Numeric(5, 1), nullable=True),
        sa.Column('upgrade_5d_sample', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('downgrade_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_1d_downgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('median_1d_downgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('avg_5d_downgrade', sa.Numeric(8, 4), nullable=True),
        sa.Column('downgrade_5d_continuation_pct', sa.Numeric(5, 1), nullable=True),
        sa.Column('downgrade_5d_sample', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('symbol', name='uq_analyst_reaction_stats_symbol'),
    )


def downgrade() -> None:
    op.drop_table('analyst_reaction_stats')
