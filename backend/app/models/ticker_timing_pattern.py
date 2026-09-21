from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TickerTimingPattern(Base):
    """A ticker's price-confirmed reporting habit (see app.services.report_timing)."""

    __tablename__ = "ticker_timing_patterns"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    pattern: Mapped[str] = mapped_column(String(10), nullable=False)  # bmo | amc | mixed
    decisive_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    bmo_share: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    rule_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
