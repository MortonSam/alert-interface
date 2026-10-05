from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TickerAlias(Base):
    """A symbol a ticker used to trade under. The ticker row kept its id and history under the new symbol
    (services/ticker_rename); requests for the old symbol redirect (main.TickerAliasMiddleware)."""
    __tablename__ = "ticker_aliases"

    old_symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    renamed_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
