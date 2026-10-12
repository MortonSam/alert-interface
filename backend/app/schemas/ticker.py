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


class TickerExit(BaseModel):
    """A stock that no longer trades (services/ticker_exits): the page shows this line and the last stored close instead of trading facts."""
    kind: str                           # services/ticker_exits kind ("taken_private")
    line: str                           # "Electronic Arts was taken private on August 4, 2026, and its stock no longer trades."
    since: date
    last_close: float | None = None     # the last stored daily close (price_bars_shadow); None when none is stored
    last_close_date: date | None = None


class TickerRead(TickerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    next_earnings_date: date | None = None
    next_earnings_source: str | None = None          # events.source of that date ("finnhub", "yfinance", ...)
    next_earnings_checked_at: datetime | None = None  # tickers.earnings_checked_at: when Finnhub was last asked
    next_earnings_confirmation: str | None = None    # "confirmed" | "estimated" | "expected_unconfirmed"
    next_earnings_note: str | None = None            # why: "confirmed: Finnhub and Yahoo Finance agree", "estimated (Finnhub)"
    # with LICENSED_DATES_ONLY and no company-confirmed date: the expected window from the company's past report dates in SEC filings
    next_earnings_window_start: date | None = None
    next_earnings_window_end: date | None = None
    next_earnings_window_source: str | None = None
    next_earnings_window_computed_at: str | None = None
    deal_note: str | None = None                     # a pending cash deal (services/pending_deals): the visitor note; the page shows plain price facts below it
    exit: TickerExit | None = None                   # set by /by-symbol when the stock no longer trades and its kind has an approved line
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
    price_history_excluded: bool = False # earnings_markers are [] because the ticker is on the RV exclusion list
    exclusion_reason: str | None = None
    bars_basis: str | None = None        # "delayed" when the 1-day bars came from the live layer; the page labels them from this
    bars_through: str | None = None      # the newest bar's own time (ISO with offset) when bars_basis is set
    delay_minutes: int | None = None


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
    quote_basis: str = "last_trade"      # last_trade | close (the stored close served when Finnhub had no answer in time) | delayed (the live layer)
    delay_minutes: int | None = None     # the source's stated delay when quote_basis is delayed; the page renders it
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
    timestamp: int | None = None  # Unix UTC (exchange last-trade time, or the session's close when quote_basis is close)
    quote_basis: str = "last_trade"   # last_trade | close | delayed
    delay_minutes: int | None = None  # the source's stated delay when quote_basis is delayed
    quote_state: str = "ok"           # ok | stale | no_data; price fields are null unless ok
    quote_reason: str | None = None   # plain language, shown in place of the price


class BatchEnrichRead(BaseModel):
    """Combined quote + expected-move + realized-vol for watchlist rows."""
    symbol: str
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    quote_ts: int | None = None       # Unix UTC (exchange last-trade time, or the session's close when quote_basis is close)
    quote_basis: str = "last_trade"   # last_trade | close
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
