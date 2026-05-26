import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import DataSource, EventType

if TYPE_CHECKING:
    from app.models.historical_reaction import HistoricalReaction
    from app.models.ticker import Ticker


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_ticker_id", "ticker_id"),
        Index("ix_events_event_date", "event_date"),
        Index("ix_events_event_type", "event_type"),
        Index("ix_events_ticker_date", "ticker_id", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable — macro/FRED events don't belong to a single ticker
    ticker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, name="event_type_enum", values_callable=lambda x: [e.value for e in x]), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource, name="data_source_enum", values_callable=lambda x: [e.value for e in x]), nullable=False, default=DataSource.MANUAL)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Flexible bag for source-specific data: EPS estimate, FDA drug name, FRED series ID, etc.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ticker: Mapped["Ticker | None"] = relationship(back_populates="events")
    historical_reactions: Mapped[list["HistoricalReaction"]] = relationship(back_populates="event")
