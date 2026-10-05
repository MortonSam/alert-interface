import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecurityRecord(Base):
    """The Intrinio security record a ticker resolves to on a date: one current row per symbol, predecessor
    rows for re-domiciled or re-listed names, and a stored_history row where no Intrinio record covers the
    stored rows (PSKY before 2025-08-07). services/security_records.py resolves and validates them."""
    __tablename__ = "security_records"
    __table_args__ = (
        UniqueConstraint("symbol", "valid_from", name="uq_security_records_symbol_valid_from"),
        Index("ix_security_records_symbol", "symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    intrinio_security_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    intrinio_ticker: Mapped[str | None] = mapped_column(Text, nullable=True)      # the ticker Intrinio files the record under (EQR's record is VMRK)
    intrinio_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # Intrinio's active flag ("recently traded") at the last refresh
    figi: Mapped[str | None] = mapped_column(Text, nullable=True)
    composite_figi: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    figi_seen: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_price_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
