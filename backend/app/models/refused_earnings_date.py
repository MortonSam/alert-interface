import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RefusedEarningsDate(Base):
    """An earnings date the seeder refused because a row within DUPLICATE_GUARD_DAYS already existed.

    Written by upsert_reaction on every refusal, so a wrong date seeded first
    cannot silently block the right one: validate lists these, and
    repair_refused_dates swaps the rows when the SEC acceptance time supports
    the refused date.
    """
    __tablename__ = "refused_earnings_dates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    refused_date: Mapped[date] = mapped_column(Date, nullable=False)        # the date the source offered
    blocking_row_date: Mapped[date] = mapped_column(Date, nullable=False)   # the stored row that refused it
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="yahoo", server_default="yahoo")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        UniqueConstraint("ticker_id", "refused_date", "blocking_row_date", name="uq_refused_earnings_dates_pair"),
    )
