import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SectorPeerSnapshot(Base):
    """Per-ticker sector peer stats, computed nightly.

    One row per (symbol, as_of_date).  The sector aggregate (avg across
    all peers in the same sector) is derived from these rows at write time
    and stored on each row so every reader sees the same number.
    """
    __tablename__ = "sector_peer_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sector: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    avg_abs_1d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    quarter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sector_avg_abs_1d: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    sector_peer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    computation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_sector_peer_snapshot_symbol_date"),
    )
