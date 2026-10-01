"""price_bars_shadow: Intrinio daily bars by security record, written nightly, read by the shadow recompute.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_bars_shadow",
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("security_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("security_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("intrinio_security_id", sa.Text(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("adj_open", sa.Float(), nullable=True),      # as Intrinio adjusted them on fetched_at; readers rebuild from factor
        sa.Column("adj_high", sa.Float(), nullable=True),
        sa.Column("adj_low", sa.Float(), nullable=True),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("adj_volume", sa.BigInteger(), nullable=True),
        sa.Column("factor", sa.Float(), nullable=False, server_default="1"),
        sa.Column("split_ratio", sa.Float(), nullable=False, server_default="1"),
        sa.Column("dividend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "date", name="pk_price_bars_shadow"),
    )
    op.create_index("ix_price_bars_shadow_record", "price_bars_shadow", ["security_record_id"])


def downgrade() -> None:
    op.drop_index("ix_price_bars_shadow_record", table_name="price_bars_shadow")
    op.drop_table("price_bars_shadow")
