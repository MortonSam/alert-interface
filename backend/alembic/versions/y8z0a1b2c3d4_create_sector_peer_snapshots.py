"""Create sector_peer_snapshots table

Per-ticker sector peer stats.  One row per (symbol, as_of_date) storing
the ticker's own avg_abs_1d, quarter_count, plus the sector-wide aggregate
so every reader sees the same number.

Revision ID: y8z0a1b2c3d4
Revises: x7y9z0a1b2c3
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "y8z0a1b2c3d4"
down_revision = "x7y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sector_peer_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("sector", sa.String(100), nullable=False, index=True),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("avg_abs_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("quarter_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sector_avg_abs_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("sector_peer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("computation_version", sa.SmallInteger(), nullable=False,
                  server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "as_of_date",
                            name="uq_sector_peer_snapshot_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("sector_peer_snapshots")
