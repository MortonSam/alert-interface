import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IVHistory(Base):
    """Daily snapshot of ATM implied volatility and realized vol per ticker.

    One row per (symbol, date) — upserted by snapshot_iv.py so re-runs are safe.

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
    # 20-day annualized realized vol on this date (0–1 decimal)
    realized_vol_20d: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    atm_strike: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_iv_history_symbol_date"),
    )
