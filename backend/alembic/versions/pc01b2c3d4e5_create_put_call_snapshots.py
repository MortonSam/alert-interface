"""Create put_call_snapshots table

Per-ticker put/call ratio stored at chain ingest time.

Revision ID: pc01b2c3d4e5
Revises: z9a1b2c3d4e5
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "pc01b2c3d4e5"
down_revision = "z9a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "put_call_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("basis", sa.String(10), nullable=False,
                  server_default="volume"),
        sa.Column("put_total", sa.Integer(), nullable=True),
        sa.Column("call_total", sa.Integer(), nullable=True),
        sa.Column("expiration_used", sa.String(10), nullable=True),
        sa.Column("computation_version", sa.SmallInteger(), nullable=False,
                  server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "snapshot_date",
                            name="uq_put_call_snapshot_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("put_call_snapshots")
