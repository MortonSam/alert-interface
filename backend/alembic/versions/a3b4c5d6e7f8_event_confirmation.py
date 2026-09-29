"""events: confirmation note, unresolved past estimates and the sources checked.

Revision ID: a3b4c5d6e7f8
Revises: z2a3b4c5d6e7
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a3b4c5d6e7f8"
down_revision = "z2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("confirmation_note", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("unresolved_since", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("sources_checked", postgresql.JSONB(), nullable=True))
    op.add_column("events", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "checked_at")
    op.drop_column("events", "sources_checked")
    op.drop_column("events", "unresolved_since")
    op.drop_column("events", "confirmation_note")
