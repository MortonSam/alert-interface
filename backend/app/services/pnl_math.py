"""Shared P&L math for option positions and direction scoring.

Used by both the Thesis Tracker (live marks + resolution) and the
Alert Picks ledger (expiration-time scoring).  Consolidates logic
that was previously duplicated across thesis.py endpoints.
"""

from __future__ import annotations


def compute_option_pnl_at_expiry(
    close: float,
    strike: float,
    spread_strike: float | None,
    cost: float,
    direction: str,
) -> tuple[float, float]:
    """Compute (pnl_dollars, pnl_pct) for a position settled at intrinsic.

    Returns dollar P&L per-contract (×100 multiplier already applied) and
    percentage P&L (0-based: -100 = total loss, +50 = 50% gain).
    """
    if direction == "bullish":
        intrinsic = max(close - strike, 0.0)
    else:
        intrinsic = max(strike - close, 0.0)

    if spread_strike is not None:
        width = abs(strike - spread_strike)
        intrinsic = min(intrinsic, width)

    pnl_dollars = round((intrinsic - cost) * 100, 2)
    pnl_pct = round(((intrinsic - cost) / cost) * 100, 2) if cost else 0.0
    return pnl_dollars, pnl_pct


def compute_spread_pnl_from_mids(
    current_mid1: float,
    current_mid2: float | None,
    entry_prem1: float,
    entry_prem2: float | None,
    contracts: int,
) -> tuple[float | None, float | None]:
    """Compute (pnl_dollars, pnl_pct) from live or intrinsic mid-prices.

    Single-leg when current_mid2/entry_prem2 are None.
    Spread when both are provided.
    Returns (None, None) if inputs are insufficient.
    """
    if current_mid2 is None or entry_prem2 is None:
        # Single leg
        pnl_dollars = (current_mid1 - entry_prem1) * contracts * 100
        pnl_pct = (current_mid1 - entry_prem1) / entry_prem1 if entry_prem1 > 0 else None
    else:
        # Spread: long leg1, short leg2
        net_current = current_mid1 - current_mid2
        net_entry = entry_prem1 - entry_prem2
        pnl_dollars = (net_current - net_entry) * contracts * 100
        pnl_pct = (net_current - net_entry) / net_entry if net_entry > 0 else None

    return (
        round(pnl_dollars, 2),
        round(pnl_pct, 4) if pnl_pct is not None else None,
    )


def compute_intrinsic_mids(
    option_type: str,
    current_price: float,
    strike1: float,
    strike2: float | None,
) -> tuple[float, float | None]:
    """Compute intrinsic mid for expired options.

    Returns (mid1, mid2) where mid2 is None if no second leg.
    """
    if option_type == "call":
        mid1 = max(0.0, current_price - strike1)
        mid2 = max(0.0, current_price - strike2) if strike2 is not None else None
    else:
        mid1 = max(0.0, strike1 - current_price)
        mid2 = max(0.0, strike2 - current_price) if strike2 is not None else None
    return mid1, mid2


def direction_correct(
    direction: str,
    entry_price: float,
    resolution_price: float,
) -> bool:
    """Was the directional call correct?"""
    if direction == "bullish":
        return resolution_price > entry_price
    elif direction == "bearish":
        return resolution_price < entry_price
    else:  # neutral — stayed within ±5%
        pct_change = abs(resolution_price - entry_price) / entry_price if entry_price else 0
        return pct_change <= 0.05


def target_reached(
    direction: str,
    entry_price: float,
    resolution_price: float,
    target_price: float,
) -> bool:
    """Did the price reach the target?"""
    if direction == "bullish":
        return resolution_price >= target_price
    elif direction == "bearish":
        return resolution_price <= target_price
    else:
        return abs(resolution_price - entry_price) <= abs(target_price - entry_price)
