import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShadowPick(Base):
    __tablename__ = "shadow_picks"
    __table_args__ = (
        Index("ix_shadow_picks_event_date", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    probability: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    threshold_used: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    would_pick: Mapped[bool] = mapped_column(Boolean, nullable=False)
    top_factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    v2_decision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    v2_pick_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_picks.id"), nullable=True,
    )
    actual_5d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
