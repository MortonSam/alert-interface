import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


COURIER_SOURCE = "courier"
SOLVER_SOURCE = "intrinio_mid"


class IVHistory(Base):
    """Daily snapshot of ATM implied volatility and realized vol per ticker.

    One row per (symbol, date, iv_source). iv_source "courier" rows are the vendor's IV from the courier chain,
    upserted by snapshot_iv.py; every reader filters on them (COURIER_SOURCE). iv_source "intrinio_mid" rows are
    the in-house solve (services/iv_solver, iv_version = IV_SOLVER_VERSION) written beside them by
    scripts/solve_atm_iv.py and served nowhere.

    TODO: Once >= 3–6 months of rows have accrued, compute true IV Rank/Percentile
    the same way as realized vol rank (trailing 252 readings, rank + percentile) and
    display both side-by-side on the ticker page. The spread between IV Rank and RV
    Rank (implied vs actual movement cost) is a useful signal for options pricing.
    """

    __tablename__ = "iv_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # ATM implied vol from the nearest >=7d expiration (0–1 decimal, e.g. 0.30 = 30%)
    atm_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    atm_iv_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)   # set whenever atm_iv is written NULL
    # 20-day annualized realized vol on this date (0–1 decimal)
    realized_vol_20d: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    atm_strike: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    iv_source: Mapped[str] = mapped_column(String(20), nullable=False, server_default=COURIER_SOURCE, default=COURIER_SOURCE)
    iv_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)        # null for courier rows
    # solver rows only: the inputs and both sides, so the number can be re-derived
    expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    atm_call_mid: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    atm_put_mid: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    solved_call_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    solved_put_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    vendor_call_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    vendor_put_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    vendor_iv: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    rate: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_to_expiry: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "date", "iv_source", name="uq_iv_history_symbol_date_source"),
    )
