"""Add ivy_train_log table

Small table recording per-training-run metrics: n_rows, positive_rate,
holdout_accuracy, holdout_n, and the reaction computation_version.
One row per nightly shadow_eval run.

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "h4i5j6k7l8m9"
down_revision = "g3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ivy_train_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("n_rows", sa.Integer, nullable=False),
        sa.Column("positive_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("holdout_accuracy", sa.Numeric(5, 4), nullable=True),
        sa.Column("holdout_n", sa.Integer, nullable=True),
        sa.Column("computation_version", sa.SmallInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ivy_train_log")
