import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AlertPick(Base):
    __tablename__ = "alert_picks"
    __table_args__ = (
        Index("ix_alert_picks_symbol_status", "symbol", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    picked_direction: Mapped[str] = mapped_column(String(20), nullable=False)  # "bullish" | "bearish"
    leans: Mapped[dict] = mapped_column(JSONB, nullable=False)  # [{signal, direction, justification}, ...]
    strategy: Mapped[str | None] = mapped_column(String(255))
    suggested_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    suggested_spread_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    suggested_target: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    expiration: Mapped[str | None] = mapped_column(String(10))  # "YYYY-MM-DD"
    cost_to_enter: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # per-contract $
    max_loss: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # per-contract $
    max_gain: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # null = unlimited
    vol_regime: Mapped[str | None] = mapped_column(String(20))
    reasoning: Mapped[str | None] = mapped_column(Text)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    algo_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1", server_default="v1")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
