"""Create magnitude_trend_snapshots table

Per-ticker magnitude trend stats: recent vs prior avg abs 1d move
and the derived trend label (increasing/decreasing/stable).

Revision ID: z9a1b2c3d4e5
Revises: y8z0a1b2c3d4
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "z9a1b2c3d4e5"
down_revision = "y8z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "magnitude_trend_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("recent_avg_abs_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("prior_avg_abs_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("recent_window", sa.SmallInteger(), nullable=False,
                  server_default="4"),
        sa.Column("prior_window", sa.SmallInteger(), nullable=False,
                  server_default="4"),
        sa.Column("trend", sa.String(20), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("computation_version", sa.SmallInteger(), nullable=False,
                  server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "as_of_date",
                            name="uq_magnitude_trend_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("magnitude_trend_snapshots")
