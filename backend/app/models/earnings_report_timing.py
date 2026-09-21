import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EarningsReportTiming(Base):
    __tablename__ = "earnings_report_timing"
    __table_args__ = (
        Index(
            "ix_ert_ticker_date",
            "ticker_id",
            "event_date",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    timing: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'unknown'"))
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'unknown'"))
    acceptance_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timing_source: Mapped[str | None] = mapped_column(String(60), nullable=True)  # rule branch, see report_timing.classify
    timing_rule_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
