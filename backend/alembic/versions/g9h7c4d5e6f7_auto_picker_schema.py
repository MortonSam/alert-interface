"""auto_picker_schema

Revision ID: g9h7c4d5e6f7
Revises: f8g6b9c3d4e5
Create Date: 2026-08-24 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g9h7c4d5e6f7'
down_revision: Union[str, None] = 'f8g6b9c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # alert_picks.source
    op.add_column('alert_picks', sa.Column('source', sa.String(20), nullable=False, server_default='manual'))

    # alert_pick_evaluations
    op.create_table(
        'alert_pick_evaluations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('symbol', sa.String(10), nullable=False, index=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('outcome', sa.String(30), nullable=False),
        sa.Column('leans', JSONB, nullable=True),
        sa.Column('alert_pick_id', UUID(as_uuid=True), sa.ForeignKey('alert_picks.id'), nullable=True),
        sa.Column('note', sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('alert_pick_evaluations')
    op.drop_column('alert_picks', 'source')
