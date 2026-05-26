"""initial schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────
    op.execute("""
        CREATE TYPE event_type_enum AS ENUM (
            'earnings', 'macro', 'fda', 'ex_dividend', 'product_launch', 'other'
        )
    """)
    op.execute("""
        CREATE TYPE data_source_enum AS ENUM (
            'yfinance', 'edgar', 'fred', 'fda', 'polygon', 'manual'
        )
    """)

    # ── tickers ───────────────────────────────────────────
    op.create_table(
        "tickers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("sector", sa.String(100)),
        sa.Column("industry", sa.String(100)),
        sa.Column("exchange", sa.String(50)),
        sa.Column("market_cap", sa.BigInteger()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_tickers_symbol", "tickers", ["symbol"], unique=True)

    # ── watchlists ────────────────────────────────────────
    op.create_table(
        "watchlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── watchlist_tickers (join) ───────────────────────────
    op.create_table(
        "watchlist_tickers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("watchlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("watchlist_id", "ticker_id", name="uq_watchlist_ticker"),
    )

    # ── events ────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # ticker_id is nullable — macro events (FRED releases) have no single ticker
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", postgresql.ENUM(name="event_type_enum", create_type=False), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source", postgresql.ENUM(name="data_source_enum", create_type=False), nullable=False, server_default="manual"),
        sa.Column("source_url", sa.Text()),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Flexible bucket for source-specific metadata (e.g. EPS estimate, FDA PDUFA drug name)
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_events_ticker_id", "events", ["ticker_id"])
    op.create_index("ix_events_event_date", "events", ["event_date"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    # Composite index for the catalyst panel query (ticker + upcoming date range)
    op.create_index("ix_events_ticker_date", "events", ["ticker_id", "event_date"])

    # ── historical_reactions ──────────────────────────────
    op.create_table(
        "historical_reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False),
        # event_id is nullable — reaction can be recorded without a linked event row
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", postgresql.ENUM(name="event_type_enum", create_type=False), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("close_before", sa.Numeric(12, 4)),   # closing price on T-1
        sa.Column("open_after", sa.Numeric(12, 4)),     # opening price on T
        sa.Column("close_after", sa.Numeric(12, 4)),    # closing price on T
        sa.Column("pct_change_1d", sa.Numeric(8, 4)),   # (close_after - close_before) / close_before
        sa.Column("pct_change_3d", sa.Numeric(8, 4)),   # T+3 close vs close_before
        sa.Column("pct_change_5d", sa.Numeric(8, 4)),   # T+5 close vs close_before
        sa.Column("volume_before", sa.BigInteger()),
        sa.Column("volume_after", sa.BigInteger()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_hist_reactions_ticker_id", "historical_reactions", ["ticker_id"])
    op.create_index("ix_hist_reactions_event_date", "historical_reactions", ["event_date"])
    op.create_index("ix_hist_reactions_ticker_type", "historical_reactions", ["ticker_id", "event_type"])


def downgrade() -> None:
    op.drop_table("historical_reactions")
    op.drop_table("events")
    op.drop_table("watchlist_tickers")
    op.drop_table("watchlists")
    op.drop_table("tickers")
    op.execute("DROP TYPE IF EXISTS event_type_enum")
    op.execute("DROP TYPE IF EXISTS data_source_enum")
