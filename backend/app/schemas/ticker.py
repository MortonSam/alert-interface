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
    index_member: bool = True


class TickerCreate(TickerBase):
    pass


class TickerUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    is_active: bool | None = None
    index_member: bool | None = None


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
    report_timing: str | None = None  # "bmo" | "amc" | "unknown"


class TickerChartRead(BaseModel):
    symbol: str
    period: str
    history: list["SparklinePoint"]
    earnings_markers: list[EarningsMarker]
    start_price: float | None = None  # reference for the period's change calc
    history_state: str = "ok"            # ok | stale | mismatch | no_data; history is [] unless ok
    history_reason: str | None = None    # why the history is withheld
    last_bar_date: str | None = None     # date of the newest bar the source returned


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
    sparkline: list[SparklinePoint]  # daily closes, chronological; [] unless history_state is ok
    quote_state: str = "ok"              # ok | stale; price fields are null when stale
    quote_reason: str | None = None
    history_state: str = "ok"            # ok | stale | mismatch | no_data
    history_reason: str | None = None
    last_bar_date: str | None = None


class BatchQuoteRead(BaseModel):
    symbol: str
    price: float | None
    change: float | None
    change_pct: float | None
    timestamp: int | None = None  # Unix UTC (exchange last-trade time)
    quote_state: str = "ok"           # ok | stale | no_data; price fields are null unless ok
    quote_reason: str | None = None   # plain language, shown in place of the price


class BatchEnrichRead(BaseModel):
    """Combined quote + expected-move + realized-vol for watchlist rows."""
    symbol: str
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    quote_ts: int | None = None       # Unix UTC (exchange last-trade time)
    expected_move_pct: float | None = None
    earnings_date: str | None = None
    rv_rank: float | None = None
    current_rv: float | None = None
    inactive: bool = False
    quote_state: str = "ok"           # ok | stale | no_data; price fields are null unless ok
    quote_reason: str | None = None


# ── Company news (Finnhub) ───────────────────────────────────────────────────

class NewsItem(BaseModel):
    headline: str
    source: str
    url: str
    datetime: int          # Unix timestamp (seconds)
    summary: str


class NewsRead(BaseModel):
    items: list[NewsItem]
