"""Add iv_history table for daily ATM IV + realized vol snapshotting

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "iv_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("atm_iv", sa.Numeric(8, 6), nullable=True),
        sa.Column("realized_vol_20d", sa.Numeric(8, 6), nullable=True),
        sa.Column("atm_strike", sa.Numeric(12, 4), nullable=True),
        sa.Column("current_price", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "date", name="uq_iv_history_symbol_date"),
    )
    op.create_index("ix_iv_history_symbol", "iv_history", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_iv_history_symbol", table_name="iv_history")
    op.drop_table("iv_history")
