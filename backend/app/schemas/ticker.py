import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class TickerBase(BaseModel):
    symbol: str = Field(..., max_length=10)
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    is_active: bool = True


class TickerCreate(TickerBase):
    pass


class TickerUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    is_active: bool | None = None


class TickerRead(TickerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    next_earnings_date: date | None = None
    created_at: datetime
    updated_at: datetime


# ── Chart response ────────────────────────────────────────────────────────────

class EarningsMarker(BaseModel):
    date: str             # "YYYY-MM-DD"
    eps_estimate: float | None = None
    eps_actual: float | None = None
    outcome: str          # "beat" | "miss" | "meet" | "unknown"
    pct_change_1d: float | None = None
    pct_change_3d: float | None = None
    pct_change_5d: float | None = None


class TickerChartRead(BaseModel):
    symbol: str
    period: str
    history: list["SparklinePoint"]
    earnings_markers: list[EarningsMarker]
    start_price: float | None = None  # reference for the period's change calc


# ── Quote response (Finnhub) ──────────────────────────────────────────────────

class SparklinePoint(BaseModel):
    date: str   # "YYYY-MM-DD"
    close: float


class TickerQuoteRead(BaseModel):
    symbol: str
    price: float | None
    change: float | None        # absolute change from prev close
    change_pct: float | None    # % change from prev close
    high: float | None          # day high
    low: float | None           # day low
    open: float | None          # day open
    prev_close: float | None
    timestamp: int | None       # Unix UTC
    sparkline: list[SparklinePoint]  # daily closes, chronological


class BatchQuoteRead(BaseModel):
    symbol: str
    price: float | None
    change: float | None
    change_pct: float | None
