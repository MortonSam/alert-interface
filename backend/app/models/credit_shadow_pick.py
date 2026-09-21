import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CreditShadowPick(Base):
    __tablename__ = "credit_shadow_picks"
    __table_args__ = (
        Index("ix_credit_shadow_picks_event_date", "event_date"),
        UniqueConstraint("symbol", "event_date", name="uq_credit_shadow_picks_symbol_event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    spot: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    expected_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    implied_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    short_put_strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    short_call_strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    long_put_strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    long_call_strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    expiration: Mapped[str] = mapped_column(String(10), nullable=False)
    credit_received: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    max_loss: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    pnl_dollars: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    stock_move_5d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
