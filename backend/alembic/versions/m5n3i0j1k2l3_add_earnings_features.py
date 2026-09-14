"""Add earnings_features table.

Revision ID: m5n3i0j1k2l3
Revises: l4m2h9i0j1k2
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "m5n3i0j1k2l3"
down_revision = "l4m2h9i0j1k2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "earnings_features",
        sa.Column("ticker_id", UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_date", sa.Date(), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        # Pre-event features
        sa.Column("beat_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("median_1d_beat", sa.Numeric(8, 4), nullable=True),
        sa.Column("median_1d_miss", sa.Numeric(8, 4), nullable=True),
        sa.Column("weighted_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("n_prior_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy_share_latest", sa.Numeric(8, 4), nullable=True),
        sa.Column("buy_share_60d_ago", sa.Numeric(8, 4), nullable=True),
        sa.Column("analyst_delta", sa.Numeric(8, 4), nullable=True),
        sa.Column("momentum_20d", sa.Numeric(8, 4), nullable=True),
        sa.Column("atm_iv", sa.Numeric(8, 6), nullable=True),
        # V1 lean replay
        sa.Column("lean_earnings", sa.String(10), nullable=True),
        sa.Column("lean_analyst", sa.String(10), nullable=True),
        sa.Column("lean_momentum", sa.String(10), nullable=True),
        sa.Column("decision", sa.String(20), nullable=True),
        # Targets
        sa.Column("actual_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_3d", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_5d", sa.Numeric(8, 4), nullable=True),
        sa.Column("outcome", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ef_symbol", "earnings_features", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_ef_symbol", table_name="earnings_features")
    op.drop_table("earnings_features")
