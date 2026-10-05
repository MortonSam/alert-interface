"""Seed stock-split history from Intrinio's price adjustments into the events table.

By default the splits come from the stored shadow bars (one query for every active ticker, no requests): a bar whose
price factor marks a split (services/corporate_actions.split_price_factor reads split_ratio, factor and dividend
together, because Intrinio is not consistent between them) is a split on that date, and the factor is inverted into
the stored "X:Y" shape. --full reads Intrinio's adjustments endpoint instead, by security
record (the current record and its predecessors), for history older than the stored bars. Spin-off and stub
factors (a side above MAX_RATIO_SIDE) are not splits and are skipped, as before. Rows are inserted once per
(ticker, date); existing rows are never rewritten.

CLI
---
    python -m app.scripts.seed_splits                 # nightly: from the stored bars
    python -m app.scripts.seed_splits --full          # the adjustments endpoint, every record, all history
    python -m app.scripts.seed_splits --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.corporate_actions import format_ratio, is_real_split_ratio, splits_from_adjustments  # noqa: F401  (format_ratio, is_real_split_ratio kept for callers)
from app.services.intrinio_client import IntrinioClient

_format_ratio = format_ratio
_is_real_split_ratio = is_real_split_ratio


async def splits_from_bars(symbols: list[str]) -> dict[str, list[dict]]:
    """{symbol: [{date, split_ratio, intrinio_split_ratio}]} from every stored bar with a split factor, one query."""
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("SELECT symbol, date, split_ratio, factor, dividend FROM price_bars_shadow WHERE (split_ratio <> 1 OR factor <> 1) AND symbol = ANY(:s) ORDER BY symbol, date"),
                                {"s": symbols})).all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(r)
    return {sym: splits_from_adjustments(rs) for sym, rs in by.items()}


async def splits_from_api(symbol: str, client: IntrinioClient) -> list[dict]:
    """All history from the adjustments endpoint, by security record: the current record and every predecessor."""
    async with AsyncSessionLocal() as s:
        ids = (await s.execute(text("SELECT intrinio_security_id FROM security_records WHERE symbol = :s AND intrinio_security_id IS NOT NULL ORDER BY valid_from"),
                               {"s": symbol})).scalars().all()
    out: dict[date, dict] = {}
    for sid in ids:
        for sp in splits_from_adjustments(await client.price_adjustments(sid)):
            out.setdefault(sp["date"], sp)
    return [out[d] for d in sorted(out)]


async def _upsert_split_event(session, ticker: Ticker, split_date: date, split_ratio: str, intrinio_split_ratio: float | None = None) -> bool:
    """Insert the split if not already present. Returns True if inserted."""
    existing = await session.scalar(select(Event.id).where(Event.ticker_id == ticker.id, Event.event_date == split_date, Event.event_type == EventType.SPLIT))
    if existing is not None:
        return False
    meta = {"split_ratio": split_ratio}
    if intrinio_split_ratio is not None:
        meta["intrinio_split_ratio"] = intrinio_split_ratio
    session.add(Event(ticker_id=ticker.id, event_type=EventType.SPLIT, event_date=split_date, title=f"{ticker.symbol} {split_ratio} Stock Split",
                      source=DataSource.INTRINIO, is_confirmed=True, metadata_=meta))
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed stock splits from Intrinio's price adjustments")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--full", action="store_true", help="read the adjustments endpoint by security record for all history")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        tickers = list((await session.execute(select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"Split history ({'adjustments endpoint, every record' if args.full else 'stored shadow bars'}): {len(tickers)} ticker(s)", flush=True)

    inserted = 0
    requests = 0
    failed: list[str] = []
    client = IntrinioClient() if args.full else None
    try:
        found = {} if args.full else await splits_from_bars([t.symbol for t in tickers])
        for t in tickers:
            try:
                splits = await splits_from_api(t.symbol, client) if args.full else found.get(t.symbol, [])
                if not splits:
                    continue
                async with AsyncSessionLocal() as session:
                    n = 0
                    for sp in splits:
                        n += await _upsert_split_event(session, t, sp["date"], sp["split_ratio"], sp.get("intrinio_split_ratio"))
                    await session.commit()
                inserted += n
            except Exception as exc:
                failed.append(f"{t.symbol}: {str(exc)[:80]}")
    finally:
        if client is not None:
            requests = client.request_count
            await client.close()
    print(f"  {inserted} split(s) inserted, {len(failed)} failed, {requests} request(s)")
    for f in failed[:10]:
        print("   ", f)
    return 1 if len(failed) > 10 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
