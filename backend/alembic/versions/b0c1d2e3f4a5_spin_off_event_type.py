"""event_type_enum gets 'spin_off': spin-off adjustments reclassified out of the split rows.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-10-05
"""
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'spin_off'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values; no-op
    pass
