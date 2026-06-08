from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ThesisCreate(BaseModel):
    symbol: str                          # looked up to ticker_id server-side
    direction: str                       # bullish | bearish | neutral
    conviction: int = Field(ge=1, le=5)  # 1–5
    catalyst: str | None = None
    price_target: float | None = None
    target_date: date
    reasoning: str | None = None
    notes: str | None = None
    # entry_price is NOT accepted from the client — always captured from live quote at creation

    # Option leg (optional) — entry_premium/entry_premium2 are server-captured from chain
    option_type: str | None = None         # "call" | "put"
    strike: float | None = None
    option_expiration: str | None = None   # "YYYY-MM-DD"
    contracts: int = 1
    strike2: float | None = None           # second leg (spread)
    spread_type: str | None = None         # "bull_call_spread" | "bear_put_spread" | etc.
    from_ai_draft: bool = False


class ThesisResolve(BaseModel):
    reflection: str
    self_grade: str                      # right | right_for_wrong_reasons | wrong
    price_override: float | None = None  # manual price if auto-capture unavailable


class ThesisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker_id: uuid.UUID
    ticker_symbol: str | None = None     # populated server-side from ticker relationship

    direction: str
    conviction: int
    catalyst: str | None
    price_target: Decimal | None
    target_date: date
    entry_price: Decimal | None          # stock price when thesis was created
    reasoning: str | None
    notes: str | None

    status: str
    resolved_at: datetime | None
    price_at_resolution: Decimal | None
    direction_correct: bool | None
    target_reached: bool | None
    self_grade: str | None
    reflection: str | None

    # Option leg
    option_type: str | None = None
    strike: Decimal | None = None
    option_expiration: date | None = None
    entry_premium: Decimal | None = None    # option premium at creation (server-captured)
    contracts: int = 1
    strike2: Decimal | None = None
    entry_premium2: Decimal | None = None
    spread_type: str | None = None
    from_ai_draft: bool = False

    # Option P&L (filled at resolution)
    option_pnl_dollars: Decimal | None = None
    option_pnl_pct: Decimal | None = None

    created_at: datetime
    updated_at: datetime

    # Computed convenience fields (not stored)
    is_due: bool = False                 # target_date <= today


class ThesisMarkRead(BaseModel):
    """Live mark-to-market for the option leg on a thesis."""
    thesis_id: uuid.UUID
    option_type: str | None
    strike: float | None
    strike2: float | None
    current_price: float | None
    current_mid1: float | None          # current mid of leg 1
    current_mid2: float | None          # current mid of leg 2 (if spread)
    entry_premium: float | None
    entry_premium2: float | None
    contracts: int
    pnl_dollars: float | None           # total P&L in dollars
    pnl_pct: float | None               # as fraction of initial debit (0.28 = +28%)
    mark_basis: str                     # "live_chain" | "intrinsic" | "not_found" | "no_option_leg"
    is_expired: bool
    mark_note: str | None               # human-readable context (expiry, error, etc.)
    as_of: str                          # ISO UTC timestamp


class ThesisStockMarkRead(BaseModel):
    """Live price mark for a stock-only thesis (no option leg).

    Separate from ThesisMarkRead — stock theses are tracked against the live
    quote, not the option chain.  The two mark types must never be mixed.
    """
    thesis_id: uuid.UUID
    current_price: float | None
    entry_price: float | None
    price_target: float | None
    pct_from_entry: float | None        # signed %, e.g. +0.96 or -2.1
    pct_to_target: float | None         # 0–100+ (% of the way; can exceed 100 if past target)
    verdict: str | None                 # "on_track" | "reversed" | "target_hit"
    direction: str
    as_of: str                          # ISO UTC timestamp
    auto_resolved: bool = False         # True if this call triggered auto-resolution


class ThesisDraftRequest(BaseModel):
    symbol: str
    direction: str                        # bullish | bearish
    aggressiveness: str                   # conservative | moderate | aggressive
    proposed_target: float | None = None  # optional — AI evaluates it for realism


class ThesisDraftRead(BaseModel):
    symbol: str
    direction: str
    aggressiveness: str
    suggested_target: float | None
    suggested_strike: float | None
    suggested_spread_strike: float | None  # second leg if spread strategy, else None
    strategy: str | None                   # e.g. "Long $315 call ($5.80 mid)"
    reasoning: str
    realism_flag: str | None               # non-null when target is beyond data support
    fact_block: dict                       # all injected facts (for transparency/verification)
    model_used: str
    generated_at: str


class ThesisDraftAlternativeRequest(BaseModel):
    symbol: str
    direction: str                           # bullish | bearish
    aggressiveness: str                      # conservative | moderate | aggressive
    budget: float                            # max cost per contract in dollars
    best_strike: float                       # leg 1 of the best play (context only)
    best_spread_strike: float | None = None  # leg 2 of best play if spread
    best_cost: float                         # cost of best play per contract (context only)


class ThesisDraftAlternativeRead(BaseModel):
    fits: bool                    # True if a good affordable alternative was found
    strategy: str | None          # e.g. "Bull call spread $305/$320 ($8.10 net debit)" — null if fits=False
    suggested_strike: float | None
    suggested_spread_strike: float | None
    cost_to_enter: float | None   # must be <= budget when fits=True; null when fits=False
    target: float | None          # data-grounded price target at same aggressiveness
    tradeoff: str | None          # honest statement of what's given up vs best play; null when fits=False
    reasoning: str | None         # 2-3 sentences citing real strikes/prices; null when fits=False
    note: str | None              # when fits=False: why nothing good fits + recommendation; null when fits=True
    model_used: str
    generated_at: str
