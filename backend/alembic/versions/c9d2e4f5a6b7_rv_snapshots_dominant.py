"""rv_snapshots: the session carrying the largest share of the 20-day realized variance (rv_math.dominant_session). When that share
is over one half the IV-versus-realized comparison and its rich/cheap label are not shown; the page says one session dominates the
window and names its date and move.

Revision ID: c9d2e4f5a6b7
Revises: b8c9d2e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c9d2e4f5a6b7"
down_revision = "b8c9d2e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rv_snapshots", sa.Column("dominant_date", sa.Date(), nullable=True))
    op.add_column("rv_snapshots", sa.Column("dominant_move_pct", sa.Numeric(8, 2), nullable=True))
    op.add_column("rv_snapshots", sa.Column("dominant_share", sa.Numeric(5, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("rv_snapshots", "dominant_share")
    op.drop_column("rv_snapshots", "dominant_move_pct")
    op.drop_column("rv_snapshots", "dominant_date")
