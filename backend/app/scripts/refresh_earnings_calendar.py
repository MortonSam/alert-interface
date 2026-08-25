"""Refresh earnings calendar from Finnhub.

One Finnhub /calendar/earnings call for today..today+60d, then match against
our active tickers.  Match window is 45 days (same quarter).  Events within
14 days of today are treated as confirmed and left unchanged.

A one-time dedup pass runs first: for each ticker with multiple future
earnings events within a 45-day cluster, all but one are deleted.

Usage
-----
    python -m app.scripts.refresh_earnings_calendar
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.finnhub_client import FinnhubClient

LOOKAHEAD_DAYS = 60
MATCH_WINDOW_DAYS = 45
CONFIRMED_HORIZON_DAYS = 14


async def _dedup_earnings(session, today: date) -> int:
    """Delete duplicate future earnings within 45-day clusters per ticker.

    Keep priority: date within 14 days of today > most recently updated row.
    Returns total deletions.
    """
    confirmed_cutoff = today + timedelta(days=CONFIRMED_HORIZON_DAYS)

    tickers = (await session.execute(
        select(Ticker).where(Ticker.is_active.is_(True))
    )).scalars().all()

    total_deleted = 0
    for ticker in tickers:
        events = (await session.execute(
            select(Event)
            .where(
                Event.ticker_id == ticker.id,
                Event.event_type == EventType.EARNINGS,
                Event.event_date >= today,
            )
            .order_by(Event.event_date)
        )).scalars().all()

        if len(events) <= 1:
            continue

        # Cluster events within 45 days of each other
        clusters: list[list[Event]] = []
        for ev in events:
            placed = False
            for cluster in clusters:
                if abs((ev.event_date - cluster[0].event_date).days) <= MATCH_WINDOW_DAYS:
                    cluster.append(ev)
                    placed = True
                    break
            if not placed:
                clusters.append([ev])

        for cluster in clusters:
            if len(cluster) <= 1:
                continue

            # Pick keeper: prefer earliest date within 14 days, else most recently updated
            near_term = [e for e in cluster if e.event_date <= confirmed_cutoff]
            if near_term:
                keeper = min(near_term, key=lambda e: e.event_date)
            else:
                keeper = max(cluster, key=lambda e: e.updated_at)

            to_delete = [e for e in cluster if e.id != keeper.id]
            for e in to_delete:
                print(f"  dedup {ticker.symbol}: deleting {e.event_date.isoformat()} "
                      f"(keeping {keeper.event_date.isoformat()})")
                await session.delete(e)
                total_deleted += 1

    await session.commit()
    return total_deleted


async def main() -> int:
    today = date.today()
    end = today + timedelta(days=LOOKAHEAD_DAYS)

    # 0. Dedup pass
    async with ScriptSessionLocal() as session:
        deleted = await _dedup_earnings(session, today)
    if deleted:
        print(f"Dedup: removed {deleted} duplicate earnings event(s).\n")

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
        # 2. Build active symbol -> ticker map
        tickers = (await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True))
        )).scalars().all()
        ticker_by_sym: dict[str, Ticker] = {t.symbol: t for t in tickers}
        active_syms = set(ticker_by_sym.keys())

        # 3. Filter to our active symbols
        relevant = [e for e in entries if e.get("symbol") in active_syms]
        print(f"  {len(relevant)} entries match active tickers.")

        confirmed_cutoff = today + timedelta(days=CONFIRMED_HORIZON_DAYS)

        inserted = 0
        updated = 0
        unchanged = 0
        kept_confirmed = 0
        insert_examples: list[str] = []
        update_examples: list[str] = []
        unchanged_examples: list[str] = []
        confirmed_examples: list[str] = []

        for entry in relevant:
            sym = entry["symbol"]
            ticker = ticker_by_sym[sym]
            try:
                edate = date.fromisoformat(entry["date"])
            except (KeyError, ValueError):
                continue

            # Look for existing future earnings event within 45-day window
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
                if existing.event_date == edate:
                    unchanged += 1
                    if len(unchanged_examples) < 5:
                        unchanged_examples.append(f"    {sym}: {edate.isoformat()}")
                elif existing.event_date <= confirmed_cutoff:
                    # Near-term: treat as confirmed, don't move
                    kept_confirmed += 1
                    if len(confirmed_examples) < 5:
                        confirmed_examples.append(
                            f"    {sym}: kept {existing.event_date.isoformat()} "
                            f"(Finnhub says {edate.isoformat()})")
                else:
                    old_date = existing.event_date.isoformat()
                    existing.event_date = edate
                    existing.source = DataSource.FINNHUB
                    updated += 1
                    if len(update_examples) < 5:
                        update_examples.append(f"    {sym}: {old_date} -> {edate.isoformat()}")
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
    print(f"  Inserted: {inserted}  Updated: {updated}  "
          f"Unchanged: {unchanged}  Kept confirmed: {kept_confirmed}")
    print(f"{'─' * 50}")

    if insert_examples:
        print(f"\n  Inserted examples:")
        print("\n".join(insert_examples))
    if update_examples:
        print(f"\n  Updated examples:")
        print("\n".join(update_examples))
    if confirmed_examples:
        print(f"\n  Kept confirmed examples:")
        print("\n".join(confirmed_examples))
    if unchanged_examples:
        print(f"\n  Unchanged examples:")
        print("\n".join(unchanged_examples))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
