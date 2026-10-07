"""eps_quarters.diluted_shares: the quarter's weighted-average diluted share count from XBRL, so validate can warn when the count
moves more than 10% between quarters with no recorded corporate action.

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d1"
down_revision = "d4e5f6a7b8c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eps_quarters", sa.Column("diluted_shares", sa.Numeric(18, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("eps_quarters", "diluted_shares")
