import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import EventType

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.ticker import Ticker


class HistoricalReaction(Base):
    __tablename__ = "historical_reactions"
    __table_args__ = (
        Index("ix_hist_reactions_ticker_id", "ticker_id"),
        Index("ix_hist_reactions_event_date", "event_date"),
        Index("ix_hist_reactions_ticker_type", "ticker_id", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    # Nullable — reaction can be stored before a linked event row exists
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, name="event_type_enum"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_before: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # T-1 close
    open_after: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))   # T open
    close_after: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # T close
    pct_change_1d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pct_change_3d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pct_change_5d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    volume_before: Mapped[int | None] = mapped_column(BigInteger)
    volume_after: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticker: Mapped["Ticker"] = relationship(back_populates="historical_reactions")
    event: Mapped["Event | None"] = relationship(back_populates="historical_reactions")
