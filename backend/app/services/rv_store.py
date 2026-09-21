"""Read helpers for the rv_snapshots table. The only way RV reaches a response.

get_servable_rv(db, symbol)      → (row | None, reason | None)
get_latest_rv(db, symbol)        → row | None
get_latest_rv_bulk(db, symbols)  → dict[symbol, row]

A symbol's RV is served only when its NEWEST snapshot:
  - is within the last 5 trading days (~7 calendar days),
  - has status == "ok", and
  - sits on a price history that passes the shared freshness test
    (last bar no more than 3 sessions before the snapshot date).
An older ok row is never served in place of a newer failing one. There is no
live fallback: callers show RV as absent, with the reason.
"""
from __future__ import annotations

from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.price_freshness import assess_history

# 5 trading days ≈ 7 calendar days
_FRESHNESS_DAYS = 7

_LATEST_SQL = sa.text("""
    SELECT DISTINCT ON (symbol)
           symbol, as_of_date, rv_20d, rv_rank, rv_percentile,
           rv_min_1y, rv_max_1y, sample_days, status, last_bar_date
    FROM rv_snapshots
    WHERE symbol = ANY(:symbols)
    ORDER BY symbol, as_of_date DESC
""")


# Visitor-facing wording for each snapshot status. Technical detail goes to the log.
_STATUS_REASONS = {
    "no_data": "Not enough recent price history to compute realized volatility",
    "insufficient": "Not enough recent price history to compute realized volatility",
    "fetch_failed": "Price data could not be retrieved, so realized volatility is unavailable",
    "data_error": "Realized volatility could not be computed reliably for this ticker",
}
_NO_SNAPSHOT = "Realized volatility has not been computed for this ticker yet"


def _why_not(row: sa.Row, cutoff: date) -> tuple[str, str] | None:
    """None when the row may be served, else (visitor reason, log detail)."""
    if row.status != "ok":
        return (
            _STATUS_REASONS.get(row.status, "Realized volatility is unavailable for this ticker"),
            f"snapshot {row.as_of_date} status={row.status} sample_days={row.sample_days}",
        )
    if row.as_of_date < cutoff:
        return ("Realized volatility has not been updated recently",
                f"snapshot {row.as_of_date} older than {_FRESHNESS_DAYS} days")
    if row.last_bar_date is not None:
        state = assess_history(row.last_bar_date, None, None, today=row.as_of_date)
        if not state.ok:
            return (state.reason, state.detail or state.state)
    return None


async def get_servable_rv(db: AsyncSession, symbol: str) -> tuple[sa.Row | None, str | None]:
    """(row, None) when RV may be shown, else (latest row or None, reason)."""
    row = (await db.execute(_LATEST_SQL, {"symbols": [symbol]})).one_or_none()
    if row is None:
        return None, _NO_SNAPSHOT
    why = _why_not(row, date.today() - timedelta(days=_FRESHNESS_DAYS))
    if why is None:
        return row, None
    print(f"[rv] {symbol}: not served ({why[1]})", flush=True)
    return None, why[0]


async def get_latest_rv(db: AsyncSession, symbol: str) -> sa.Row | None:
    """Single-symbol lookup. Returns the servable row, or None."""
    return (await get_servable_rv(db, symbol))[0]


async def get_latest_rv_bulk(
    db: AsyncSession, symbols: list[str],
) -> dict[str, sa.Row]:
    """Multi-symbol lookup. Returns {symbol: row} for symbols whose RV may be shown."""
    if not symbols:
        return {}
    cutoff = date.today() - timedelta(days=_FRESHNESS_DAYS)
    result = await db.execute(_LATEST_SQL, {"symbols": symbols})
    return {row.symbol: row for row in result.all() if _why_not(row, cutoff) is None}
