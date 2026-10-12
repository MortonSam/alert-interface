"""The pricing desk's card and verdict rows as the API serves them (services/pricing_desk builds them). Every field typed."""
from __future__ import annotations

from pydantic import BaseModel


class PricingLeg(BaseModel):
    kind: str                    # "call" | "put"
    side: str                    # "buy" | "sell"
    strike: float
    bid: float | None
    ask: float | None


class PricingStructure(BaseModel):
    legs: list[PricingLeg]
    cost_per_contract: float     # net debit per contract; negative for a credit
    max_loss_per_contract: float
    breakeven_pct: float
    p_profit: float
    ev_per_100: float            # expected dollars per $100 risked at the real bid and ask
    ev_per_100_full_spread: float
    expected_payoff_method: str


class PriorMove(BaseModel):
    date: str
    pct_1d: float


class PricingCardRead(BaseModel):
    symbol: str
    computed_at: str
    computation_version: int
    report_date: str
    report_confirmation: str | None
    chain_date: str | None
    chain_source: str | None
    expiration: str
    spot: float
    atm_strike: float
    implied_move_pct: float
    typical_move_pct: float
    prior_n: int
    prior_moves: list[PriorMove]
    p_beyond_implied: float
    structures: dict[str, PricingStructure | None]
    verdict: str                 # "no_edge" | "possible_edge" (machine values; the page renders the approved wording)
    verdict_structure: str | None


class PricingVerdictRead(BaseModel):
    symbol: str
    report_date: str
    computed_at: str
    computation_version: int
    verdict: str
    verdict_structure: str | None
    ev_long_call: float | None
    ev_long_straddle: float | None
    ev_bull_call_spread: float | None
    ev_iron_condor: float | None
    settled_at: str | None
    actual_move_pct: float | None
    settled_long_call: float | None
    settled_long_straddle: float | None
    settled_bull_call_spread: float | None
    settled_iron_condor: float | None
