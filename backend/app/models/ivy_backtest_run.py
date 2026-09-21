import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, SmallInteger, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IvyBacktestRun(Base):
    """One run of backtest_v2 on the chosen rule. /ivy renders the latest."""

    __tablename__ = "ivy_backtest_runs"
    __table_args__ = (Index("ix_ivy_backtest_runs_run_at", "run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    momentum_cutoff_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    min_prior_quarters: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    folds: Mapped[list] = mapped_column(JSONB, nullable=False)
    setups: Mapped[int] = mapped_column(Integer, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)
    hit_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    base_n: Mapped[int] = mapped_column(Integer, nullable=False)
    base_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
