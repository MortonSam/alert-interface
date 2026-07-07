"""Read helpers for the rv_snapshots table.

get_latest_rv(db, symbol)       → row | None
get_latest_rv_bulk(db, symbols) → dict[symbol, row]

Returns the most recent rv_snapshots row per symbol ONLY when:
  - as_of_date is within the last 5 trading days (~7 calendar days)
  - status == "ok"
Otherwise returns None; the caller decides on fallback.
"""
from __future__ import annotations

from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# 5 trading days ≈ 7 calendar days
_FRESHNESS_DAYS = 7


async def get_latest_rv(db: AsyncSession, symbol: str) -> sa.Row | None:
    """Single-symbol lookup. Returns the newest fresh ok row, or None."""
    cutoff = date.today() - timedelta(days=_FRESHNESS_DAYS)
    stmt = sa.text("""
        SELECT symbol, as_of_date, rv_20d, rv_rank, rv_percentile,
               rv_min_1y, rv_max_1y, sample_days, status
        FROM rv_snapshots
        WHERE symbol = :symbol
          AND as_of_date >= :cutoff
          AND status = 'ok'
        ORDER BY as_of_date DESC
        LIMIT 1
    """)
    result = await db.execute(stmt, {"symbol": symbol, "cutoff": cutoff})
    return result.one_or_none()


async def get_latest_rv_bulk(
    db: AsyncSession, symbols: list[str],
) -> dict[str, sa.Row]:
    """Multi-symbol lookup. Returns {symbol: row} for symbols with fresh ok data."""
    if not symbols:
        return {}
    cutoff = date.today() - timedelta(days=_FRESHNESS_DAYS)
    # DISTINCT ON (symbol) ORDER BY as_of_date DESC picks the latest per symbol
    stmt = sa.text("""
        SELECT DISTINCT ON (symbol)
               symbol, as_of_date, rv_20d, rv_rank, rv_percentile,
               rv_min_1y, rv_max_1y, sample_days, status
        FROM rv_snapshots
        WHERE symbol = ANY(:symbols)
          AND as_of_date >= :cutoff
          AND status = 'ok'
        ORDER BY symbol, as_of_date DESC
    """)
    result = await db.execute(stmt, {"symbols": symbols, "cutoff": cutoff})
    return {row.symbol: row for row in result.all()}
