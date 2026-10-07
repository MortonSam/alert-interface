"""release_eps.xbrl_note: why a release figure was judged without an XBRL figure (the quarter exists in XBRL only as a derived
annual-less-three-quarters figure, which is never compared). Set with xbrl_checked_at and no xbrl_eps; validate counts such rows
as checked, never as overdue.

Revision ID: f6a7b8c9d2e4
Revises: e5f6a7b8c9d1
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d2e4"
down_revision = "e5f6a7b8c9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("release_eps", sa.Column("xbrl_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("release_eps", "xbrl_note")
