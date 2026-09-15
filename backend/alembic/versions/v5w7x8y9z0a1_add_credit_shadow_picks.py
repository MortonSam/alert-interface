"""Add credit_shadow_picks table

Revision ID: v5w7x8y9z0a1
Revises: u4v6w7x8y9z0
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v5w7x8y9z0a1"
down_revision = "u4v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_shadow_picks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("spot", sa.Numeric(12, 4), nullable=False),
        sa.Column("expected_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("implied_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("short_put_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("short_call_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("long_put_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("long_call_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("expiration", sa.String(10), nullable=False),
        sa.Column("credit_received", sa.Numeric(10, 4), nullable=False),
        sa.Column("max_loss", sa.Numeric(10, 2), nullable=False),
        sa.Column("exit_date", sa.Date, nullable=False),
        sa.Column("close_value", sa.Numeric(10, 4), nullable=True),
        sa.Column("pnl_dollars", sa.Numeric(12, 2), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("stock_move_5d", sa.Numeric(8, 4), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_shadow_picks_event_date", "credit_shadow_picks", ["event_date"])


def downgrade() -> None:
    op.drop_index("ix_credit_shadow_picks_event_date", table_name="credit_shadow_picks")
    op.drop_table("credit_shadow_picks")
