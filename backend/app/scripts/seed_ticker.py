"""Seed a ticker and its next earnings event from yfinance.

Usage:
    python -m app.scripts.seed_ticker AAPL
    python -m app.scripts.seed_ticker AAPL MSFT NVDA
    make seed TICKER=AAPL
    make seed TICKER="AAPL MSFT NVDA"
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker


# ── yfinance helpers ──────────────────────────────────────────────────────────

@dataclass
class TickerData:
    symbol: str
    name: str | None
    sector: str | None
    industry: str | None
    exchange: str | None
    market_cap: int | None
    next_earnings: date | None


def _coerce_date(val: object) -> date | None:
    """Convert a pandas Timestamp / datetime / str to a plain date."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if hasattr(val, "date"):          # pandas Timestamp or datetime
        return val.date()
    if isinstance(val, str):
        try:
            from datetime import datetime
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _next_earnings_from_calendar(t: yf.Ticker) -> date | None:
    today = date.today()
    cal = t.calendar
    if not cal or not isinstance(cal, dict):
        return None
    raw = cal.get("Earnings Date")
    if raw is None:
        return None
    vals = raw if isinstance(raw, list) else [raw]
    for v in vals:
        d = _coerce_date(v)
        if d and d >= today:
            return d
    return None


def _next_earnings_from_df(t: yf.Ticker) -> date | None:
    """Fallback: use the earnings_dates DataFrame (yfinance 0.2+)."""
    today = date.today()
    try:
        import pandas as pd
        df = t.earnings_dates
        if df is None or df.empty:
            return None
        # Index is tz-aware; normalize to date for comparison
        future = df[df.index.normalize() >= pd.Timestamp(today, tz="UTC")]
        if future.empty:
            return None
        return future.index.min().date()
    except Exception:
        return None


def fetch_ticker_data(symbol: str) -> TickerData:
    t = yf.Ticker(symbol)
    info = t.info or {}

    next_earnings: date | None = None
    try:
        next_earnings = _next_earnings_from_calendar(t)
    except Exception:
        pass
    if next_earnings is None:
        try:
            next_earnings = _next_earnings_from_df(t)
        except Exception:
            pass

    return TickerData(
        symbol=symbol.upper(),
        name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        exchange=info.get("exchange"),
        market_cap=info.get("marketCap"),
        next_earnings=next_earnings,
    )


# ── DB upserts ────────────────────────────────────────────────────────────────

async def upsert_ticker(session, data: TickerData) -> Ticker:
    stmt = (
        pg_insert(Ticker)
        .values(
            symbol=data.symbol,
            name=data.name,
            sector=data.sector,
            industry=data.industry,
            exchange=data.exchange,
            market_cap=data.market_cap,
            is_active=True,
        )
        .on_conflict_do_update(
            index_elements=["symbol"],
            set_=dict(
                name=data.name,
                sector=data.sector,
                industry=data.industry,
                exchange=data.exchange,
                market_cap=data.market_cap,
            ),
        )
        .returning(Ticker)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def upsert_earnings_event(session, ticker: Ticker, earnings_date: date) -> tuple[Event, bool]:
    """Return (event, created). Matches on ticker_id + event_date + event_type."""
    existing = await session.scalar(
        select(Event).where(
            Event.ticker_id == ticker.id,
            Event.event_date == earnings_date,
            Event.event_type == EventType.EARNINGS,
        )
    )
    if existing:
        existing.title = f"{ticker.symbol} Earnings"
        existing.source = DataSource.YFINANCE
        return existing, False

    event = Event(
        ticker_id=ticker.id,
        event_type=EventType.EARNINGS,
        event_date=earnings_date,
        title=f"{ticker.symbol} Earnings",
        source=DataSource.YFINANCE,
        is_confirmed=False,
        metadata_={},
    )
    session.add(event)
    return event, True


# ── Main ──────────────────────────────────────────────────────────────────────

async def seed(symbol: str) -> None:
    print(f"\n── {symbol} {'─' * (44 - len(symbol))}")

    print("  Fetching yfinance data...")
    try:
        data = fetch_ticker_data(symbol)
    except Exception as exc:
        print(f"  ERROR: yfinance fetch failed — {exc}")
        return

    print(f"  name       : {data.name}")
    print(f"  sector     : {data.sector}")
    print(f"  industry   : {data.industry}")
    print(f"  exchange   : {data.exchange}")
    print(f"  market_cap : {data.market_cap:,}" if data.market_cap else "  market_cap : None")
    print(f"  earnings   : {data.next_earnings}")

    async with AsyncSessionLocal() as session:
        ticker = await upsert_ticker(session, data)
        print(f"  ✓ ticker upserted  → id={ticker.id}")

        if data.next_earnings:
            event, created = await upsert_earnings_event(session, ticker, data.next_earnings)
            action = "inserted" if created else "updated"
            print(f"  ✓ event {action}   → {event.event_date} ({event.event_type.value})")
        else:
            print("  ⚠  no upcoming earnings date found")

        await session.commit()


async def main() -> None:
    symbols = [s.upper() for s in sys.argv[1:]]
    if not symbols:
        print("Usage: python -m app.scripts.seed_ticker SYMBOL [SYMBOL ...]")
        sys.exit(1)

    for sym in symbols:
        await seed(sym)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    asyncio.run(main())
