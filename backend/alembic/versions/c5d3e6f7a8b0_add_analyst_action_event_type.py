"""add_analyst_action_event_type

Revision ID: c5d3e6f7a8b0
Revises: b4c2d5e6f8a9
Create Date: 2026-07-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5d3e6f7a8b0'
down_revision: Union[str, None] = 'b4c2d5e6f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'analyst_action'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values; no-op
    pass
