"""Add data_version to research_notes

Track which reaction computation version was current when the note was
generated, so staleness can be detected after a version bump.

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = "f2g3h4i5j6k7"
down_revision = "e1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_notes",
        sa.Column("data_version", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    op.drop_column("research_notes", "data_version")
