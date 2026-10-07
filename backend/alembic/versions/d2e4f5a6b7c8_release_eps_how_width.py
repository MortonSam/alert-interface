"""release_eps.how widens to 64 characters: "net income per share row, basic then diluted" is 44, and seven agreed figures (COST, CSCO,
GRMN, INCY, MNST, NTAP, VLTO) failed to store on 2026-10-07 with a string-truncation error.

Revision ID: d2e4f5a6b7c8
Revises: c9d2e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e4f5a6b7c8"
down_revision = "c9d2e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("release_eps", "how", type_=sa.String(64), existing_type=sa.String(40), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("release_eps", "how", type_=sa.String(40), existing_type=sa.String(64), existing_nullable=False)
