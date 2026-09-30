"""The implied move, computed one way for every page.

Build a Trade's fact block, the ticker page's options bundle and /expected-move all take the at-the-money
straddle from the same chain and divide it by the same spot through straddle_implied_move(), so the same
expiry and spot give the same number everywhere. The span the move covers is named from the data: the
expiry, and the days from the chain's own date to it, never from the request time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def mid_or_last(bid, ask, last) -> float | None:
    """A contract's price: the bid/ask midpoint when both are quoted, else the last trade, else None."""
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


@dataclass(frozen=True)
class ImpliedMove:
    atm_strike: float
    straddle: float        # dollars per share: the ATM call plus the ATM put
    pct: float             # straddle / spot, a 0-1 decimal
    low: float             # spot - straddle
    high: float            # spot + straddle


def straddle_implied_move(calls: list[dict], puts: list[dict], spot: float | None) -> ImpliedMove | None:
    """The ATM straddle's implied move for `spot`, or None without a priced ATM pair."""
    if not spot or spot <= 0:
        return None
    strikes = {c.get("strike") for c in calls} & {p.get("strike") for p in puts}
    strikes.discard(None)
    if not strikes:
        return None
    atm = min(strikes, key=lambda s: abs(s - spot))
    call = next((c for c in calls if c.get("strike") == atm), None)
    put = next((p for p in puts if p.get("strike") == atm), None)
    cp = mid_or_last(call.get("bid"), call.get("ask"), call.get("lastPrice")) if call else None
    pp = mid_or_last(put.get("bid"), put.get("ask"), put.get("lastPrice")) if put else None
    if not cp or not pp:
        return None
    straddle = cp + pp
    return ImpliedMove(atm_strike=atm, straddle=straddle, pct=straddle / spot, low=spot - straddle, high=spot + straddle)


def span_days(chain_last_trade, expiration: str | None) -> int | None:
    """Days the implied move covers: from the chain's own date to the expiry. None when either is missing."""
    if not chain_last_trade or not expiration:
        return None
    try:
        start = date.fromisoformat(str(chain_last_trade)[:10])
        end = date.fromisoformat(str(expiration)[:10])
    except ValueError:
        return None
    return (end - start).days
