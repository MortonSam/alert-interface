"""Moves beside the market (Discover, 2026-10-15): SPY's move on a session, from SPY's own stored bars or its stored quote, and the
rule that says a list of stocks moved with the market that session (thresholds.MARKET_DAY_MIN_SPY_PCT and MARKET_DAY_MIN_SHARE).

SPY's daily move is printed as traded, the session's close against the previous session's close, unadjusted, the same way the
tape prints each stock's dominant move (services/rv_store). A session without both SPY closes has no SPY figure, never an estimate.
"""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from app.thresholds import MARKET_DAY_MIN_SHARE, MARKET_DAY_MIN_SPY_PCT

BENCHMARK = "SPY"

_SPY_MOVES_SQL = sa.text("""
    SELECT d.date, round(CAST(((d.close / p.close) - 1) * 100 AS numeric), 2) AS pct
    FROM price_bars_shadow d
    JOIN LATERAL (SELECT close FROM price_bars_shadow WHERE symbol = d.symbol AND date < d.date ORDER BY date DESC LIMIT 1) p ON true
    WHERE d.symbol = :s AND d.date = ANY(:dates) AND d.close IS NOT NULL AND p.close > 0
""")


async def spy_moves(db, dates: set[date]) -> dict[str, float]:
    """{ISO date: SPY's move that session in percent} for each date with both closes stored."""
    if not dates:
        return {}
    rows = (await db.execute(_SPY_MOVES_SQL, {"s": BENCHMARK, "dates": sorted(dates)})).all()
    return {r.date.isoformat(): float(r.pct) for r in rows if r.pct is not None}


def with_market(moves: list[float | None], spy_move_pct: float | None) -> dict | None:
    """Pure: {spy_move_pct, same_way, total, direction} when SPY moved at least MARKET_DAY_MIN_SPY_PCT and at least
    MARKET_DAY_MIN_SHARE of `moves` went the same way; None otherwise (no SPY figure, a quiet market, or a split list)."""
    ms = [m for m in moves if m is not None and m != 0]
    if spy_move_pct is None or abs(spy_move_pct) < MARKET_DAY_MIN_SPY_PCT or not ms:
        return None
    same = sum(1 for m in ms if (m > 0) == (spy_move_pct > 0))
    if same < MARKET_DAY_MIN_SHARE * len(ms):
        return None
    return {"spy_move_pct": spy_move_pct, "same_way": same, "total": len(ms), "direction": "up" if spy_move_pct > 0 else "down"}
