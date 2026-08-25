"""Refresh earnings calendar from Finnhub.

One Finnhub /calendar/earnings call for today..today+60d, then match against
our active tickers.  For each row: if an existing earnings Event for that
ticker has event_date within 3 days, update it; otherwise insert.

Usage
-----
    python -m app.scripts.refresh_earnings_calendar
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.finnhub_client import FinnhubClient

LOOKAHEAD_DAYS = 60
MATCH_WINDOW_DAYS = 3


async def main() -> int:
    today = date.today()
    end = today + timedelta(days=LOOKAHEAD_DAYS)

    # 1. Fetch calendar from Finnhub
    finnhub = FinnhubClient()
    try:
        raw = await finnhub.get_earnings_calendar(today.isoformat(), end.isoformat())
    finally:
        await finnhub.close()

    entries = raw.get("earningsCalendar", [])
    print(f"Finnhub returned {len(entries)} earnings calendar entries.")

    if not entries:
        print("Nothing to process.")
        return 0

    async with ScriptSessionLocal() as session:
        # 2. Build active symbol → ticker map
        tickers = (await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True))
        )).scalars().all()
        ticker_by_sym: dict[str, Ticker] = {t.symbol: t for t in tickers}
        active_syms = set(ticker_by_sym.keys())

        # 3. Filter to our active symbols
        relevant = [e for e in entries if e.get("symbol") in active_syms]
        print(f"  {len(relevant)} entries match active tickers.")

        inserted = 0
        updated = 0
        unchanged = 0
        insert_examples: list[str] = []
        update_examples: list[str] = []
        unchanged_examples: list[str] = []

        for entry in relevant:
            sym = entry["symbol"]
            ticker = ticker_by_sym[sym]
            try:
                edate = date.fromisoformat(entry["date"])
            except (KeyError, ValueError):
                continue

            # Look for existing earnings event within ±3 days
            window_start = edate - timedelta(days=MATCH_WINDOW_DAYS)
            window_end = edate + timedelta(days=MATCH_WINDOW_DAYS)
            existing = await session.scalar(
                select(Event).where(
                    Event.ticker_id == ticker.id,
                    Event.event_type == EventType.EARNINGS,
                    Event.event_date >= window_start,
                    Event.event_date <= window_end,
                )
            )

            if existing:
                if existing.event_date != edate:
                    old_date = existing.event_date.isoformat()
                    existing.event_date = edate
                    existing.source = DataSource.FINNHUB
                    updated += 1
                    if len(update_examples) < 5:
                        update_examples.append(f"    {sym}: {old_date} → {edate.isoformat()}")
                else:
                    unchanged += 1
                    if len(unchanged_examples) < 5:
                        unchanged_examples.append(f"    {sym}: {edate.isoformat()}")
            else:
                session.add(Event(
                    ticker_id=ticker.id,
                    event_type=EventType.EARNINGS,
                    event_date=edate,
                    title=f"{sym} Earnings",
                    source=DataSource.FINNHUB,
                    is_confirmed=False,
                    metadata_={},
                ))
                inserted += 1
                if len(insert_examples) < 5:
                    insert_examples.append(f"    {sym}: {edate.isoformat()}")

        await session.commit()

    print(f"\n{'─' * 50}")
    print(f"  Inserted: {inserted}  Updated: {updated}  Unchanged: {unchanged}")
    print(f"{'─' * 50}")

    if insert_examples:
        print(f"\n  Inserted examples:")
        print("\n".join(insert_examples))
    if update_examples:
        print(f"\n  Updated examples:")
        print("\n".join(update_examples))
    if unchanged_examples:
        print(f"\n  Unchanged examples:")
        print("\n".join(unchanged_examples))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
