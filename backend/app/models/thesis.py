import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Numeric, SmallInteger, String, Text, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.ticker import Ticker


class ThesisDirection:
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ThesisStatus:
    OPEN = "open"
    RESOLVED = "resolved"
    NEEDS_MANUAL_RESOLUTION = "needs_manual_resolution"


class SelfGrade:
    RIGHT = "right"
    RIGHT_FOR_WRONG_REASONS = "right_for_wrong_reasons"
    WRONG = "wrong"


class Thesis(Base):
    __tablename__ = "theses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False, index=True)

    # ── Bet fields ─────────────────────────────────────────────────────────────
    direction: Mapped[str] = mapped_column(
        Enum("bullish", "bearish", "neutral", name="thesis_direction_enum"),
        nullable=False,
    )
    conviction: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1–5
    catalyst: Mapped[str | None] = mapped_column(Text)
    price_target: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # captured at creation from live quote
    reasoning: Mapped[str | None] = mapped_column(Text)

    # ── Status ─────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        Enum("open", "resolved", "needs_manual_resolution", name="thesis_status_enum"),
        nullable=False,
        default="open",
        server_default="open",
    )

    # ── Resolution fields (filled when resolved) ───────────────────────────────
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NOTE: price_at_resolution is "price when user evaluated the thesis at/after target_date,"
    # NOT a precise close on the exact target date (no stored price history available).
    price_at_resolution: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)   # auto-computed from prices
    target_reached: Mapped[bool | None] = mapped_column(Boolean)      # auto-computed; independent of direction_correct
    self_grade: Mapped[str | None] = mapped_column(
        Enum("right", "right_for_wrong_reasons", "wrong", name="self_grade_enum"),
    )
    reflection: Mapped[str | None] = mapped_column(Text)  # always manual

    # ── Option leg (optional — for tracking structured trades) ─────────────────
    option_type: Mapped[str | None] = mapped_column(String(8))          # "call" | "put"
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    option_expiration: Mapped[date | None] = mapped_column(Date)
    entry_premium: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))   # mid at creation
    contracts: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    strike2: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))         # second leg (spread)
    entry_premium2: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    spread_type: Mapped[str | None] = mapped_column(String(32))
    from_ai_draft: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # ── Option P&L (filled at resolution) ─────────────────────────────────────
    option_pnl_dollars: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    option_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ticker: Mapped["Ticker"] = relationship()
