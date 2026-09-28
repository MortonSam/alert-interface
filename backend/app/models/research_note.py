import uuid
from decimal import Decimal
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.ticker import Ticker


class ResearchNote(Base):
    __tablename__ = "research_notes"
    __table_args__ = (
        UniqueConstraint("ticker_id", name="uq_research_notes_ticker"),
        Index("ix_research_notes_ticker_id", "ticker_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source_filings: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # Verification (nullable — populated after generation by a separate Opus call)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # generation + verification, from the stored token counts and the price table in research_cost
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    structured_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    data_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="complete")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="research_note")
