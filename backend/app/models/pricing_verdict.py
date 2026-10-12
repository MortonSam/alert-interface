import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PricingVerdict(Base):
    """Ivy v3's ledger of verdicts: one row per stock and report, written by the pricing desk the first night it prices the report
    (later nights update the expected values until the report), settled after the report from the stored post-report chain."""
    __tablename__ = "pricing_verdicts"
    __table_args__ = (UniqueConstraint("symbol", "report_date", name="uq_pricing_verdicts_symbol_report"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    computation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict_structure: Mapped[str | None] = mapped_column(String(20))
    ev_long_call: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ev_long_straddle: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ev_bull_call_spread: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ev_iron_condor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    legs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)      # each structure's legs and entry cost, so settlement can close them
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_move_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    settled_long_call: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    settled_long_straddle: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    settled_bull_call_spread: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    settled_iron_condor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
