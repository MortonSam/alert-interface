"""EPS actual and estimate on the earnings event itself, with source and fetched date (the night of the report, not a week later).

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("eps_actual", sa.Numeric(10, 4), nullable=True))
    op.add_column("events", sa.Column("eps_estimate", sa.Numeric(10, 4), nullable=True))
    op.add_column("events", sa.Column("eps_source", sa.String(20), nullable=True))
    op.add_column("events", sa.Column("eps_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("eps_fetched_at", "eps_source", "eps_estimate", "eps_actual"):
        op.drop_column("events", col)
