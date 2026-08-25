"""add market_cap_updated_at and finnhub data source

Revision ID: h0i8d5e6f7g8
Revises: g9h7c4d5e6f7
Create Date: 2026-08-25 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h0i8d5e6f7g8'
down_revision: Union[str, None] = 'g9h7c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickers', sa.Column('market_cap_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE data_source_enum ADD VALUE IF NOT EXISTS 'finnhub'")


def downgrade() -> None:
    op.drop_column('tickers', 'market_cap_updated_at')
    # PostgreSQL does not support removing enum values; 'finnhub' remains harmless.
