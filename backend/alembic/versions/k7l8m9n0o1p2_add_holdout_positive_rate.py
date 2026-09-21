"""Add holdout_positive_rate to ivy_train_log.

Stores the holdout set's base positive rate alongside holdout_accuracy,
so accuracy can be compared to a meaningful baseline.

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "k7l8m9n0o1p2"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ivy_train_log",
        sa.Column("holdout_positive_rate", sa.Numeric(5, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ivy_train_log", "holdout_positive_rate")
