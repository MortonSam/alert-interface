import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RVSnapshot(Base):
    __tablename__ = "rv_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    rv_20d: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    rv_rank: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    rv_percentile: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    rv_min_1y: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    rv_max_1y: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    sample_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_rv_snapshot_symbol_date"),
        Index("ix_rv_snapshot_date_rank", "as_of_date", "rv_rank"),
    )
