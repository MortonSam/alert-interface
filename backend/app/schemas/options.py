from __future__ import annotations
from pydantic import BaseModel


class OptionContractRead(BaseModel):
    strike: float
    bid: float | None
    ask: float | None
    last_price: float | None
    volume: int | None
    open_interest: int | None
    implied_volatility: float | None   # 0–1 decimal (0.30 = 30%)
    is_atm: bool
    data_quality_flag: str | None = None  # null = trustworthy; else short reason string


class OptionsChainRead(BaseModel):
    symbol: str
    expiration: str
    current_price: float | None
    calls: list[OptionContractRead]
    puts: list[OptionContractRead]
    available_expirations: list[str]
    as_of: str   # ISO UTC


class HistoricalMoveStats(BaseModel):
    avg_abs_move_pct: float   # 0–1 decimal (0.052 = 5.2%)
    max_abs_move_pct: float
    min_abs_move_pct: float
    sample_size: int
    above_expected: int   # past earnings where |1d move| > implied expected move
    below_expected: int


class ExpectedMoveRead(BaseModel):
    symbol: str
    current_price: float | None
    expected_move_pct: float | None      # 0–1 decimal
    expected_move_dollars: float | None
    implied_range_low: float | None
    implied_range_high: float | None
    expiration_used: str | None          # "YYYY-MM-DD"
    earnings_date: str | None            # "YYYY-MM-DD"
    days_expiration_past_earnings: int | None  # how many calendar days after earnings the expiration falls
    straddle_price: float | None
    atm_strike: float | None
    historical_stats: HistoricalMoveStats | None
    plain_summary: str | None            # plain-English sentence for non-options-fluent users
    data_quality_note: str | None
    as_of: str
