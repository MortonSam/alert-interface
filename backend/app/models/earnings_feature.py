import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EarningsFeature(Base):
    """Pre-event feature row for each (ticker, earnings date).

    One row per historical earnings event.  All features use only data
    available *before* the event (strict no-leakage).  Targets record
    what actually happened afterward.
    """

    __tablename__ = "earnings_features"
    __table_args__ = (
        Index("ix_ef_symbol", "symbol"),
    )

    # ── Keys ────────────────────────────────────────────────────────────────
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)

    # ── Known-before-event features ─────────────────────────────────────────
    beat_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))
    median_1d_beat: Mapped[float | None] = mapped_column(Numeric(8, 4))
    median_1d_miss: Mapped[float | None] = mapped_column(Numeric(8, 4))
    weighted_1d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    n_prior_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buy_share_latest: Mapped[float | None] = mapped_column(Numeric(8, 4))
    buy_share_60d_ago: Mapped[float | None] = mapped_column(Numeric(8, 4))
    analyst_delta: Mapped[float | None] = mapped_column(Numeric(8, 4))
    momentum_20d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    prior_avg_abs_1d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    analyst_net_90d: Mapped[int | None] = mapped_column(Integer)
    atm_iv: Mapped[float | None] = mapped_column(Numeric(8, 6))

    # ── Stage 2 features (5d horizon) ────────────────────────────────────────
    prior_avg_abs_5d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    prior_n: Mapped[int | None] = mapped_column(Integer)
    prior_up_5d_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))

    # ── V1 lean replay ──────────────────────────────────────────────────────
    lean_earnings: Mapped[str | None] = mapped_column(String(10))   # bullish/bearish/neutral
    lean_analyst: Mapped[str | None] = mapped_column(String(10))
    lean_momentum: Mapped[str | None] = mapped_column(String(10))
    decision: Mapped[str | None] = mapped_column(String(20))        # bullish/bearish/mixed

    # ── Targets (post-event actuals) ────────────────────────────────────────
    actual_1d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    actual_3d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    actual_5d: Mapped[float | None] = mapped_column(Numeric(8, 4))
    outcome: Mapped[str | None] = mapped_column(String(10))         # BEAT/MISS/MEET/UNKNOWN

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
