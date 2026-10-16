"""put_call_snapshots.expirations_used: every expiration whose volume a version-4 ratio sums (compute_put_call), so the receipt can
name them. expiration_used keeps the nearest one.

Revision ID: f3c4d5e6f7a8
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f3c4d5e6f7a8"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("put_call_snapshots", sa.Column("expirations_used", postgresql.ARRAY(sa.String(10)), nullable=True))


def downgrade() -> None:
    op.drop_column("put_call_snapshots", "expirations_used")
