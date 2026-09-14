"""Add prior_avg_abs_5d, prior_n, prior_up_5d_rate to earnings_features.

Revision ID: o7p5k2l3m4n5
Revises: n6o4j1k2l3m4
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "o7p5k2l3m4n5"
down_revision = "n6o4j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("earnings_features", sa.Column("prior_avg_abs_5d", sa.Numeric(8, 4), nullable=True))
    op.add_column("earnings_features", sa.Column("prior_n", sa.Integer(), nullable=True))
    op.add_column("earnings_features", sa.Column("prior_up_5d_rate", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("earnings_features", "prior_up_5d_rate")
    op.drop_column("earnings_features", "prior_n")
    op.drop_column("earnings_features", "prior_avg_abs_5d")
