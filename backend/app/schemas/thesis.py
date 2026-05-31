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
