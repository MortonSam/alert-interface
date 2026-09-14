"""Add prior_avg_abs_1d and analyst_net_90d to earnings_features.

Revision ID: n6o4j1k2l3m4
Revises: m5n3i0j1k2l3
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "n6o4j1k2l3m4"
down_revision = "m5n3i0j1k2l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("earnings_features", sa.Column("prior_avg_abs_1d", sa.Numeric(8, 4), nullable=True))
    op.add_column("earnings_features", sa.Column("analyst_net_90d", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("earnings_features", "analyst_net_90d")
    op.drop_column("earnings_features", "prior_avg_abs_1d")
