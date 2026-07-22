"""add_alert_picks

Revision ID: e7f5a8b9c2d3
Revises: d6e4f7a8b9c1
Create Date: 2026-07-22 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7f5a8b9c2d3'
down_revision: Union[str, None] = 'd6e4f7a8b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'alert_picks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(10), nullable=False, index=True),
        sa.Column('picked_direction', sa.String(20), nullable=False),
        sa.Column('leans', postgresql.JSONB(), nullable=False),
        sa.Column('strategy', sa.String(255), nullable=True),
        sa.Column('suggested_strike', sa.Numeric(12, 4), nullable=True),
        sa.Column('suggested_spread_strike', sa.Numeric(12, 4), nullable=True),
        sa.Column('suggested_target', sa.Numeric(12, 4), nullable=True),
        sa.Column('expiration', sa.String(10), nullable=True),
        sa.Column('cost_to_enter', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_loss', sa.Numeric(10, 2), nullable=True),
        sa.Column('max_gain', sa.Numeric(10, 2), nullable=True),
        sa.Column('vol_regime', sa.String(20), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('entry_price', sa.Numeric(12, 4), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
    )
    op.create_index('ix_alert_picks_symbol_status', 'alert_picks', ['symbol', 'status'])


def downgrade() -> None:
    op.drop_index('ix_alert_picks_symbol_status', table_name='alert_picks')
    op.drop_table('alert_picks')
