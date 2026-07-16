"""add_split_event_type

Revision ID: a3b1c4d5e6f7
Revises: 7c6a9226a1a9
Create Date: 2026-07-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3b1c4d5e6f7'
down_revision: Union[str, None] = '7c6a9226a1a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'split'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values; no-op
    pass
