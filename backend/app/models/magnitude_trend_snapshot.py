import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MagnitudeTrendSnapshot(Base):
    """Per-ticker magnitude trend stats, computed nightly.

    Stores the recent and prior window averages plus the derived trend label.
    The threshold rule stays in thresholds.py; only the raw trend string is stored.
    """
    __tablename__ = "magnitude_trend_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    recent_avg_abs_1d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    prior_avg_abs_1d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    recent_window: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="4")
    prior_window: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="4")
    trend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    computation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_magnitude_trend_symbol_date"),
    )
