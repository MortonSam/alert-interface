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
    entry_price: Decimal | None          # price when thesis was created
    reasoning: str | None

    status: str
    resolved_at: datetime | None
    price_at_resolution: Decimal | None  # price when evaluated at/after target_date
    direction_correct: bool | None       # auto-computed: did price move the predicted direction?
    target_reached: bool | None          # auto-computed: did price hit/exceed price_target?
    self_grade: str | None
    reflection: str | None

    created_at: datetime
    updated_at: datetime

    # Computed convenience fields (not stored)
    is_due: bool = False                 # target_date <= today


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
