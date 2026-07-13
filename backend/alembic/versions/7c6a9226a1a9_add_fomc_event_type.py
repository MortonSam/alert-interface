"""add_fomc_event_type

Revision ID: 7c6a9226a1a9
Revises: 2ef0b62a3ae6
Create Date: 2026-07-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c6a9226a1a9'
down_revision: Union[str, None] = '2ef0b62a3ae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'fomc'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values; no-op
    pass
