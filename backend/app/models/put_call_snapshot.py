import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PutCallSnapshot(Base):
    """Per-ticker put/call ratio snapshot, computed at chain ingest time.

    Uses the same expiration as the implied-move hero (nearest post-earnings).
    """
    __tablename__ = "put_call_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    ratio: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    basis: Mapped[str] = mapped_column(String(10), nullable=False, server_default="volume")
    put_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_used: Mapped[str | None] = mapped_column(String(10), nullable=True)
    computation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_date", name="uq_put_call_snapshot_symbol_date"),
    )
