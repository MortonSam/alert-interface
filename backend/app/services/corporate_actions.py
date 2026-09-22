"""Recorded corporate-action dates (splits and ex-dividends) from the events table.

One source for every consumer that needs to know whether a price gap on a date
is explained by a corporate action: the RV guard in rv_math and any reaction
pipeline that shares its exclusion.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ACTION_EVENT_TYPES = ("split", "ex_dividend")


async def load_action_dates(session: AsyncSession, symbols: list[str]) -> dict[str, set[date]]:
    """{symbol: {dates with a recorded split or ex-dividend}} for the given symbols."""
    if not symbols:
        return {}
    rows = (await session.execute(
        text("""
            SELECT t.symbol, e.event_date
            FROM events e
            JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = ANY(:symbols) AND e.event_type = ANY(:types)
        """),
        {"symbols": list(symbols), "types": list(ACTION_EVENT_TYPES)},
    )).all()
    out: dict[str, set[date]] = {s: set() for s in symbols}
    for symbol, event_date in rows:
        out.setdefault(symbol, set()).add(event_date)
    return out
