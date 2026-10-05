"""Daily bars for every computation: the stored Intrinio shadow bars, read by symbol through the security record map.

price_bars_shadow holds raw bars per symbol and date, each written under the security record that covered the
date (scripts/shadow_price_bars.py), with Intrinio's per-day adjustment factor. Readers here rebuild the adjusted
series from the raw bars and the factors of every later day (price_bars_shadow.adjusted_frame), so a split or
dividend after the fetch adjusts the past the same way yfinance's auto_adjust did. SPY is stored too and gives the
seeders their session calendar.

Sync readers serve the seeders and executors (they open their own short connection); async readers take a session.
Bulk readers take many symbols in one query; the record map (security_records) is loaded once per process and
answers every stored-history question without a round trip. Nothing here fetches from the network: an empty frame
means no stored bar, and the caller says so.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import settings
from app.services.price_bars_shadow import adjusted_frame

HISTORY_PAD_BEFORE_DAYS = 30     # the seeders' window: lookback less this, through today plus HISTORY_PAD_AFTER_DAYS
HISTORY_PAD_AFTER_DAYS = 2
INTRADAY_PERIODS = ("1d", "7d")  # chart periods that stay on yfinance intraday bars
PERIOD_DAYS = {"5d": 7, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827, "10y": 3653}

_SQL = "SELECT date, open, high, low, close, volume, factor, split_ratio FROM price_bars_shadow WHERE symbol = :s{more} ORDER BY date"
_sync_engine = None


def _engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database_url_sync, poolclass=NullPool)
    return _sync_engine


def _frame(rows, start: date | None, end: date | None) -> pd.DataFrame:
    """Adjust over every stored row from `start` on (later factors adjust earlier bars), then cut at `end`."""
    df = adjusted_frame([dict(r._mapping) if hasattr(r, "_mapping") else dict(r) for r in rows])
    if end is not None and not df.empty:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def bars_sync(symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Adjusted daily bars (Open, High, Low, Close, Volume; dated index) for [start, end]."""
    more, params = "", {"s": symbol}
    if start is not None:
        more, params["a"] = " AND date >= :a", start
    with _engine().connect() as conn:
        rows = conn.execute(text(_SQL.format(more=more)), params).all()
    return _frame(rows, start, end)


async def bars(session, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    more, params = "", {"s": symbol}
    if start is not None:
        more, params["a"] = " AND date >= :a", start
    rows = (await session.execute(text(_SQL.format(more=more)), params)).all()
    return _frame(rows, start, end)


def history_sync(symbol: str, lookback: date) -> pd.DataFrame:
    """The seeders' frame: from lookback less HISTORY_PAD_BEFORE_DAYS through today plus HISTORY_PAD_AFTER_DAYS."""
    return bars_sync(symbol, lookback - timedelta(days=HISTORY_PAD_BEFORE_DAYS), date.today() + timedelta(days=HISTORY_PAD_AFTER_DAYS))


def bulk_closes_sync(symbols: list[str], start: date) -> dict[str, pd.DataFrame]:
    """{symbol: DataFrame[Close, Volume]} adjusted, for the realized-vol job; symbols without bars are absent."""
    return {sym: df[["Close", "Volume"]] for sym, df in bulk_bars_sync(symbols, start).items()}


def bulk_bars_sync(symbols: list[str], start: date | None = None, end: date | None = None) -> dict[str, pd.DataFrame]:
    """{symbol: adjusted bars} for many symbols in one query; symbols without bars are absent."""
    more, params = "", {"syms": list(symbols)}
    if start is not None:
        more, params["a"] = " AND date >= :a", start
    with _engine().connect() as conn:
        rows = conn.execute(text("SELECT symbol, date, open, high, low, close, volume, factor, split_ratio FROM price_bars_shadow "
                                 f"WHERE symbol = ANY(:syms){more} ORDER BY symbol, date"), params).all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(r)
    return {sym: df for sym, rs in by.items() if not (df := _frame(rs, start, end)).empty}


def closes_sync(symbol: str, start: date) -> pd.DataFrame | None:
    df = bars_sync(symbol, start)
    return df[["Close", "Volume"]] if not df.empty else None


def _as_date(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def close_on_date_sync(symbol: str, on) -> float | None:
    """The official close on that date, as traded (unadjusted); None when no bar is stored for it."""
    with _engine().connect() as conn:
        v = conn.execute(text("SELECT close FROM price_bars_shadow WHERE symbol = :s AND date = :d"), {"s": symbol, "d": _as_date(on)}).scalar()
    return round(float(v), 4) if v is not None else None


async def close_on_date(session, symbol: str, on) -> float | None:
    v = (await session.execute(text("SELECT close FROM price_bars_shadow WHERE symbol = :s AND date = :d"), {"s": symbol, "d": _as_date(on)})).scalar()
    return round(float(v), 4) if v is not None else None


def _period_start(period: str, today: date) -> date | None:
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "max":
        return None
    days = PERIOD_DAYS.get(period)
    if days is None:
        raise ValueError(f"unknown daily period {period!r}")
    return today - timedelta(days=days)


def daily_closes_sync(symbol: str, period: str = "1mo", today: date | None = None) -> list[dict]:
    """[{date, close}] adjusted closes for the period, oldest first, for sparklines. [] without bars."""
    df = bars_sync(symbol, _period_start(period, today or date.today()))
    return [{"date": idx.strftime("%Y-%m-%d"), "close": float(c)} for idx, c in zip(df.index, df["Close"]) if pd.notna(c)]


def chart_history_daily_sync(symbol: str, period: str, today: date | None = None) -> dict:
    """The chart's daily series: {"history": [{date, close}], "start_price": first close or None}. Intraday periods are not served here."""
    if period in INTRADAY_PERIODS:
        raise ValueError(f"{period} is an intraday period: yfinance serves it")
    history = daily_closes_sync(symbol, period, today)
    return {"history": history, "start_price": history[0]["close"] if history else None}


# ── the record map: security_records loaded once per process ─────────────────

_RECORDS_SQL = """select symbol, intrinio_security_id, figi, composite_figi, name, valid_from, valid_to, role, source from security_records"""


class RecordMap:
    """Every security record, by symbol, loaded once per process. Answers stored-history questions without a query."""

    def __init__(self, rows):
        from app.services.security_records import Record
        self.by: dict[str, list] = {}
        for r in rows:
            self.by.setdefault(r[0], []).append(Record(*r))

    def stored_history_floor(self, symbol: str) -> date | None:
        """The first day of the symbol's earliest stored_history span, or None."""
        starts = [r.valid_from for r in self.by.get(symbol, []) if r.role == "stored_history"]
        return min(starts) if starts else None

    def stored_history_dates(self, symbol: str, event_dates, sessions) -> set[date]:
        """The event dates (of those given) whose row rests on a stored_history span: the event day or the session
        before it falls in a span (security_records.rests_on_stored_history)."""
        import numpy as np
        from app.services.security_records import rests_on_stored_history
        records = self.by.get(symbol, [])
        if not any(r.role == "stored_history" for r in records):
            return set()
        out = set()
        for d in event_dates:
            earlier = sessions[sessions < d] if sessions is not None and len(sessions) else np.array([])
            before = earlier[-1] if len(earlier) else None
            if rests_on_stored_history(records, d, before):
                out.add(d)
        return out


_record_map: RecordMap | None = None


async def record_map(session) -> RecordMap:
    """The process's record map, loaded on first use (one query per process)."""
    global _record_map
    if _record_map is None:
        _record_map = RecordMap((await session.execute(text(_RECORDS_SQL))).all())
    return _record_map


def record_map_sync() -> RecordMap:
    global _record_map
    if _record_map is None:
        with _engine().connect() as conn:
            _record_map = RecordMap(conn.execute(text(_RECORDS_SQL)).all())
    return _record_map


def reset_record_map() -> None:
    """Forget the cached map (tests, or after the records step rewrites the table in the same process)."""
    global _record_map
    _record_map = None


async def stored_history_dates(session, symbol: str, event_dates, sessions) -> set[date]:
    return (await record_map(session)).stored_history_dates(symbol, event_dates, sessions)


async def stored_history_floor(session, symbol: str) -> date | None:
    return (await record_map(session)).stored_history_floor(symbol)


async def mark_stored_history(session, ticker_id, event_type, dates: set[date]) -> int:
    """Stamp existing rows on those dates as stored_history without touching their values."""
    if not dates:
        return 0
    res = await session.execute(text("""UPDATE historical_reactions SET price_source = 'stored_history'
                                        WHERE ticker_id = :t AND event_type = :e AND event_date = ANY(:d)"""),
                                {"t": ticker_id, "e": event_type.value if hasattr(event_type, "value") else str(event_type), "d": sorted(dates)})
    return res.rowcount
