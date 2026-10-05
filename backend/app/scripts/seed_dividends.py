"""Seed ex-dividend dates from Intrinio's price adjustments into the events table.

By default the dates come from the stored shadow bars (price_bars_shadow.dividend, one query, no requests): a bar
with a cash dividend is an ex-dividend date, and the amount stored is that cash per share (metadata.dividend_amount,
basis per_share). The nightly reads the last WINDOW_DAYS; --full reads Intrinio's adjustments endpoint by security
record (current and predecessors) for all history. Rows are inserted once per (ticker, date); existing rows are
never rewritten.

Intrinio's price adjustments are past adjustments only. A declared future ex-dividend date is not in this plan's
data (the dividends endpoint is not licensed), so the forward "Ex-Div" catalyst is not seeded here; rows that other
sources wrote stay as they are.

CLI
---
    python -m app.scripts.seed_dividends                # nightly: the last WINDOW_DAYS from the stored bars
    python -m app.scripts.seed_dividends --full         # every stored bar, then the adjustments endpoint for every record
    python -m app.scripts.seed_dividends --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.corporate_actions import dividends_from_adjustments
from app.services.intrinio_client import IntrinioClient

WINDOW_DAYS = 14          # the nightly looks this far back on the bars; the ex-date is on the bar, so a few days of slack is plenty
DIVIDEND_BASIS = "per_share"


async def dividends_from_bars(symbols: list[str], since: date | None) -> dict[str, list[dict]]:
    """{symbol: [{date, amount}]} from every stored bar with a cash dividend on or after `since`, one query."""
    more = " AND date >= :since" if since else ""
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(f"SELECT symbol, date, dividend FROM price_bars_shadow WHERE dividend <> 0 AND symbol = ANY(:s){more} ORDER BY symbol, date"),
                                {"s": symbols, **({"since": since} if since else {})})).all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(r)
    return {sym: dividends_from_adjustments(rs) for sym, rs in by.items()}


async def dividends_from_api(symbol: str, client: IntrinioClient) -> list[dict]:
    async with AsyncSessionLocal() as s:
        ids = (await s.execute(text("SELECT intrinio_security_id FROM security_records WHERE symbol = :s AND intrinio_security_id IS NOT NULL ORDER BY valid_from"),
                               {"s": symbol})).scalars().all()
    out: dict[date, dict] = {}
    for sid in ids:
        for dv in dividends_from_adjustments(await client.price_adjustments(sid)):
            out.setdefault(dv["date"], dv)
    return [out[d] for d in sorted(out)]


async def _upsert_dividend_event(session, ticker: Ticker, ex_date: date, dividend_amount: float | None) -> bool:
    """Insert the ex-dividend date if not already present. Returns True if inserted."""
    existing = await session.scalar(select(Event.id).where(Event.ticker_id == ticker.id, Event.event_date == ex_date, Event.event_type == EventType.EX_DIVIDEND))
    if existing is not None:
        return False
    meta = {"basis": DIVIDEND_BASIS}
    if dividend_amount is not None:
        meta["dividend_amount"] = dividend_amount
    session.add(Event(ticker_id=ticker.id, event_type=EventType.EX_DIVIDEND, event_date=ex_date, title=f"{ticker.symbol} Ex-Dividend",
                      source=DataSource.INTRINIO, is_confirmed=True, metadata_=meta))
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ex-dividend dates from Intrinio's price adjustments")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--full", action="store_true", help="every stored bar, then the adjustments endpoint by security record")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        tickers = list((await session.execute(select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    if args.limit:
        tickers = tickers[:args.limit]
    since = None if args.full else date.today() - timedelta(days=WINDOW_DAYS)
    print(f"Dividend calendar (stored shadow bars{' then the adjustments endpoint' if args.full else f', last {WINDOW_DAYS} days'}): {len(tickers)} ticker(s)", flush=True)

    inserted = 0
    requests = 0
    failed: list[str] = []
    found = await dividends_from_bars([t.symbol for t in tickers], since)
    client = IntrinioClient() if args.full else None
    try:
        for t in tickers:
            try:
                divs = {d["date"]: d for d in found.get(t.symbol, [])}
                if args.full:
                    for d in await dividends_from_api(t.symbol, client):
                        divs.setdefault(d["date"], d)
                if not divs:
                    continue
                async with AsyncSessionLocal() as session:
                    n = 0
                    for d in sorted(divs):
                        n += await _upsert_dividend_event(session, t, d, divs[d]["amount"])
                    await session.commit()
                inserted += n
            except Exception as exc:
                failed.append(f"{t.symbol}: {str(exc)[:80]}")
    finally:
        if client is not None:
            requests = client.request_count
            await client.close()
    print(f"  {inserted} ex-dividend date(s) inserted, {len(failed)} failed, {requests} request(s)")
    for f in failed[:10]:
        print("   ", f)
    return 1 if len(failed) > 10 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
