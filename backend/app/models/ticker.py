import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.historical_reaction import HistoricalReaction
    from app.models.research_note import ResearchNote
    from app.models.watchlist import WatchlistTicker


class Ticker(Base):
    __tablename__ = "tickers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    exchange: Mapped[str | None] = mapped_column(String(50))
    market_cap: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    index_member: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list["Event"]] = relationship(back_populates="ticker")
    historical_reactions: Mapped[list["HistoricalReaction"]] = relationship(back_populates="ticker")
    watchlist_items: Mapped[list["WatchlistTicker"]] = relationship(back_populates="ticker")
    research_note: Mapped["ResearchNote | None"] = relationship(back_populates="ticker", uselist=False)
