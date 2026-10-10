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

# The dominant session's move is printed as traded: that day's close against the previous session's close, unadjusted, the same
# figure a quote prints for that day. The stored dominant_move_pct is dividend-adjusted (it comes from the adjusted log returns the
# variance uses), so on an ex-dividend day it differs from the day's printed move (AT&T, Oct 9, 2026: -9.81% adjusted against
# -10.82% as traded, a $0.2775 dividend). Without both stored closes the move is absent, never the adjusted figure.
_LATEST_SQL = sa.text("""
    SELECT DISTINCT ON (r.symbol)
           r.symbol, r.as_of_date, r.rv_20d, r.rv_rank, r.rv_percentile,
           r.rv_min_1y, r.rv_max_1y, r.sample_days, r.status, r.last_bar_date,
           r.dominant_date, r.dominant_share,
           r.dominant_move_pct AS dominant_move_adjusted_pct,
           CASE WHEN d.close IS NOT NULL AND p.close > 0 THEN round(CAST(((d.close / p.close) - 1) * 100 AS numeric), 2) END AS dominant_move_pct
    FROM rv_snapshots r
    LEFT JOIN price_bars_shadow d ON d.symbol = r.symbol AND d.date = r.dominant_date
    LEFT JOIN LATERAL (SELECT close FROM price_bars_shadow WHERE symbol = r.symbol AND date < r.dominant_date
                       ORDER BY date DESC LIMIT 1) p ON true
    WHERE r.symbol = ANY(:symbols)
    ORDER BY r.symbol, r.as_of_date DESC
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


def single_session_dominates(row) -> bool:
    """One session holds more than rv_math.DOMINANT_SHARE of the window's realized variance: the IV-versus-realized comparison is not shown."""
    from app.services.rv_math import DOMINANT_SHARE
    share = getattr(row, "dominant_share", None)
    return share is not None and float(share) > DOMINANT_SHARE


def dominant_note(row) -> str | None:
    """"one session dominates the 20-day window: Oct 5, 2026 (+33.5%)", for the surfaces that would have compared IV with realized."""
    if not single_session_dominates(row):
        return None
    from app.services.briefing import fmt_date
    move = getattr(row, "dominant_move_pct", None)
    return f"one session dominates the 20-day window: {fmt_date(row.dominant_date)}" + (f" ({float(move):+.1f}%)" if move is not None else "")


def single_session_dominates(row) -> bool:
    """One session holds more than rv_math.DOMINANT_SHARE of the window's realized variance: the IV-versus-realized comparison is not shown."""
    from app.services.rv_math import DOMINANT_SHARE
    share = getattr(row, "dominant_share", None)
    return share is not None and float(share) > DOMINANT_SHARE


def dominant_note(row) -> str | None:
    """"one session dominates the 20-day window: Oct 5, 2026 (+33.5%)", for the surfaces that would have compared IV with realized."""
    if not single_session_dominates(row):
        return None
    from app.services.briefing import fmt_date
    move = getattr(row, "dominant_move_pct", None)
    return f"one session dominates the 20-day window: {fmt_date(row.dominant_date)}" + (f" ({float(move):+.1f}%)" if move is not None else "")


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
