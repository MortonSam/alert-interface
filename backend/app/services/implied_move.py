"""The implied move, computed one way for every page.

Build a Trade's fact block, the ticker page's options bundle and /expected-move all take the at-the-money
straddle from the same chain and divide it by the same spot through straddle_implied_move(), so the same
expiry and spot give the same number everywhere. The span the move covers is named from the data: the
expiry, and the days from the chain's own date to it, never from the request time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


MAX_STRADDLE_SPREAD_PCT = 100.0     # the ATM straddle's combined bid-ask spread, as a percent of its mid, above which the move is paused
WIDE_QUOTES_NOTE = ("The expected move for this stock is paused until the next update. "
                    "Its options quotes are too wide right now to give a reliable number.")


def straddle_spread_pct(call: dict | None, put: dict | None) -> float | None:
    """The call's and put's bid-ask spreads together as a percent of the two mids together; None without a two-sided quote
    on both legs."""
    legs = []
    for c in (call, put):
        bid, ask = (c or {}).get("bid"), (c or {}).get("ask")
        if bid is None or ask is None or ask <= 0 or bid < 0 or ask < bid:
            return None
        legs.append((float(bid), float(ask)))
    mid = sum((b + a) / 2 for b, a in legs)
    return sum(a - b for b, a in legs) / mid * 100 if mid > 0 else None


def too_wide(call: dict | None, put: dict | None) -> bool:
    pct = straddle_spread_pct(call, put)
    return pct is not None and pct > MAX_STRADDLE_SPREAD_PCT


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


def atm_pair(calls: list[dict], puts: list[dict], spot: float | None) -> tuple[dict | None, dict | None]:
    """The call and put at the strike nearest `spot` that both sides list."""
    if not spot or spot <= 0:
        return None, None
    strikes = {c.get("strike") for c in calls} & {p.get("strike") for p in puts}
    strikes.discard(None)
    if not strikes:
        return None, None
    atm = min(strikes, key=lambda s: abs(s - spot))
    return next((c for c in calls if c.get("strike") == atm), None), next((p for p in puts if p.get("strike") == atm), None)


def wide_quotes(calls: list[dict], puts: list[dict], spot: float | None) -> bool:
    """The ATM straddle's quotes are too wide to show a move (MAX_STRADDLE_SPREAD_PCT)."""
    return too_wide(*atm_pair(calls, puts, spot))


def straddle_implied_move(calls: list[dict], puts: list[dict], spot: float | None, gate: bool = True) -> ImpliedMove | None:
    """The ATM straddle's implied move for `spot`, or None without a priced ATM pair, or (gate) when its combined bid-ask
    spread is above MAX_STRADDLE_SPREAD_PCT of its mid: callers then say so with WIDE_QUOTES_NOTE (wide_quotes)."""
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
    if gate and too_wide(call, put):
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


def implied_move_allowed(confirmation: str | None) -> bool:
    """Pure: an implied move is shown only against a report date the company has confirmed. On an estimated or unresolved
    date the straddle prices a report that may not happen (FDX's Oct 12, 2026 estimate when the company had set Oct 28), so the
    strip question, the Overview clause, the Discover options-against-typical line and Ask Ivy's implied-move facts are all
    absent. `confirmation` is next_earnings.level_of: "confirmed", "estimated" or "expected_unconfirmed"."""
    return confirmation == "confirmed"
