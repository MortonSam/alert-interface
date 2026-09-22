import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MATCH_STATUSES = ("matched", "off_by_split", "unmatched", "no_fact", "no_filing")


class EpsBasisCheck(Base):
    """One stored earnings row's actual EPS checked against EDGAR XBRL diluted EPS.

    matched      stored actual equals the XBRL figure within 0.01: the actual is GAAP
    off_by_split stored actual equals it after a recorded split factor
    unmatched    an XBRL quarter exists but the figures differ: likely adjusted / FFO
    no_fact      the filer has no EPS fact ending within 120 days before the event
    no_filing    no CIK or no companyfacts for the ticker
    """
    __tablename__ = "eps_basis_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    stored_actual: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    xbrl_eps: Mapped[float | None] = mapped_column(Numeric(10, 4))
    xbrl_tag: Mapped[str | None] = mapped_column(String(80))          # an EPS_TAGS entry, or derived_q4:<tag> (up to 60 chars)
    xbrl_period_end: Mapped[date | None] = mapped_column(Date)
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)
    split_factor: Mapped[float | None] = mapped_column(Numeric(8, 4))   # set for off_by_split
    estimate_status: Mapped[str | None] = mapped_column(String(16))      # the estimate against the same XBRL quarter
    # The estimate matches GAAP and the actual does not, by more than
    # BASIS_MISMATCH_FRACTION of the estimate: the two were reported on
    # different bases and no Beat/Miss can be read from them.
    basis_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker_id", "event_date", name="uq_eps_basis_checks_ticker_event"),
    )
