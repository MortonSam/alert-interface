"""Store the last price bar behind each RV snapshot.

last_bar_date / last_bar_close let validate and the read endpoints detect a
ticker whose price history stopped updating or belongs to another instrument,
without a live fetch.

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "n0o1p2q3r4s5"
down_revision = "m9n0o1p2q3r4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rv_snapshots", sa.Column("last_bar_date", sa.Date, nullable=True))
    op.add_column("rv_snapshots", sa.Column("last_bar_close", sa.Numeric(12, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("rv_snapshots", "last_bar_close")
    op.drop_column("rv_snapshots", "last_bar_date")
