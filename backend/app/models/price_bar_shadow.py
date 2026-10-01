import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PriceBarShadow(Base):
    """One Intrinio daily bar per symbol and date, fetched by security record id (scripts/shadow_price_bars.py).

    open..volume are as traded that day. adj_* are Intrinio's adjusted values at fetch time and go stale after a
    later split or dividend; services/price_bars_shadow.adjusted_frame rebuilds the adjusted series from the raw
    bars and the per-day factor, which is what every reader uses."""
    __tablename__ = "price_bars_shadow"
    __table_args__ = (Index("ix_price_bars_shadow_record", "security_record_id"),)

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    security_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("security_records.id", ondelete="SET NULL"), nullable=True)
    intrinio_security_id: Mapped[str] = mapped_column(Text, nullable=False)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    adj_open: Mapped[float | None] = mapped_column(Float)
    adj_high: Mapped[float | None] = mapped_column(Float)
    adj_low: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    adj_volume: Mapped[int | None] = mapped_column(BigInteger)
    factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    split_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    dividend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
