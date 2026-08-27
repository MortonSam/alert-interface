import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalystRecommendation(Base):
    __tablename__ = "analyst_recommendations"
    __table_args__ = (
        UniqueConstraint("ticker_id", "period", name="uq_analyst_rec_ticker_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False, index=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    strong_buy: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    buy: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    hold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sell: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    strong_sell: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
