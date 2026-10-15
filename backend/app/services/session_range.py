"""The ticker header's day high and low, from that session's own bars (2026-10-15).

The header used the quote vendor's "h" and "l", which can carry the prior close (TSLA on 2026-10-12 showed a high equal to the
prior session's close). The range now comes from the bars of the session the quote traded in: the stored daily bar for that
session when the nightly has written it (price_bars_shadow, read through services/price_bars), else that session's 5-minute bars
from the intraday chart source (services/live_data.intraday_chart, the accepted exception for intraday bars), else nothing. A
range is shown only when it holds the quote's price, so a high below the last trade never reaches the screen.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime

from app.services.live_data import NY

INTRADAY_TIMEOUT_SECONDS = 8.0
PRICE_TOLERANCE = 0.005          # a quote may sit this share outside the bars' range (the last bar's close is up to 5 minutes old)


@dataclass(frozen=True)
class SessionRange:
    high: float
    low: float
    session: date
    source: str                  # "daily bar" | "intraday bars"


def session_of(ts: int | None) -> date | None:
    """Pure: the New York session a last-trade time belongs to."""
    return datetime.fromtimestamp(int(ts), NY).date() if ts else None


def range_from_bars(highs: list[float | None], lows: list[float | None]) -> tuple[float, float] | None:
    """Pure: the session's high and low from its bars, None without a usable bar."""
    hs = [float(h) for h in highs if h is not None and float(h) > 0]
    ls = [float(x) for x in lows if x is not None and float(x) > 0]
    if not hs or not ls or max(hs) < min(ls):
        return None
    return max(hs), min(ls)


def holds_price(high: float, low: float, price: float | None) -> bool:
    """Pure: the range contains the quote's price, within PRICE_TOLERANCE."""
    if price is None:
        return True
    return low * (1 - PRICE_TOLERANCE) <= price <= high * (1 + PRICE_TOLERANCE)


def _stored_bar(symbol: str, session: date) -> tuple[float, float] | None:
    from app.services import price_bars
    df = price_bars.bars_sync(symbol, session, session)
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    if df.index[-1].date() != session:
        return None
    return range_from_bars([row.get("High")], [row.get("Low")])


async def session_range(symbol: str, ts: int | None, price: float | None) -> SessionRange | None:
    """The day's high and low for the session the quote traded in, or None (shown as absent)."""
    session = session_of(ts)
    if session is None:
        return None
    loop = asyncio.get_event_loop()
    try:
        got = await loop.run_in_executor(None, _stored_bar, symbol, session)
    except Exception:
        got = None
    source = "daily bar"
    if got is None:
        from app.services.live_data import intraday_chart
        try:
            chart = await asyncio.wait_for(intraday_chart(symbol, session, None), INTRADAY_TIMEOUT_SECONDS)
        except Exception:
            chart = None
        if chart:
            got = range_from_bars(chart.get("highs") or [], chart.get("lows") or [])
        source = "intraday bars"
    if got is None or not holds_price(got[0], got[1], price):
        return None
    return SessionRange(high=got[0], low=got[1], session=session, source=source)
