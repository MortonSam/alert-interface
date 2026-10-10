"""The quote a visitor gets when Finnhub has no answer in time: the last stored close from the Intrinio bars.

Shaped like Finnhub's quote (c, d, dp, h, l, o, pc, t) so every reader takes it unchanged, plus basis "close" so the page
labels it as a close rather than a last trade. Its time `t` is that session's close on the New York clock (16:00, or 13:00
on an early-close day), never the request time.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import price_bars
from app.services.trading_calendar import is_half_day

TRADE_BASIS, CLOSE_BASIS = "last_trade", "close"
BASIS_LABELS = {TRADE_BASIS: "last trade", CLOSE_BASIS: "close"}      # mirrored by frontend/src/lib/freshness.ts quoteBasisLabel
LOOKBACK_DAYS = 15
NY = ZoneInfo("America/New_York")


def close_time_unix(d: date) -> int:
    """Pure: the session's closing time as Unix UTC: 16:00 New York, 13:00 on an early close."""
    return int(datetime(d.year, d.month, d.day, 13 if is_half_day(d) else 16, 0, tzinfo=NY).timestamp())


def quote_from_bars(rows: list[tuple[date, float, float | None, float | None, float | None]]) -> dict:
    """Pure: (date, close, open, high, low) rows, oldest first, to a Finnhub-shaped quote on the newest close."""
    if not rows:
        return {"c": None, "d": None, "dp": None, "h": None, "l": None, "o": None, "pc": None, "t": None, "basis": CLOSE_BASIS}
    d, close, o, h, l = rows[-1]
    prev = rows[-2][1] if len(rows) >= 2 else None
    change = round(close - prev, 4) if prev else None
    return {"c": close, "d": change, "dp": round(change / prev * 100, 4) if prev and change is not None else None,
            "h": h, "l": l, "o": o, "pc": prev, "t": close_time_unix(d), "basis": CLOSE_BASIS}


def stored_close_quote_sync(symbol: str, today: date | None = None) -> dict:
    # as traded, so the change against the previous close is the day's printed move on an ex-dividend day too (price_bars.raw_closes_sync)
    return quote_from_bars(price_bars.raw_closes_sync(symbol, (today or date.today()) - timedelta(days=LOOKBACK_DAYS)))


def _f(v) -> float | None:
    try:
        return None if v is None or v != v else float(v)
    except (TypeError, ValueError):
        return None


async def stored_close_quote(symbol: str) -> dict:
    return await asyncio.to_thread(stored_close_quote_sync, symbol.upper())
