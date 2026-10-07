"""Compute per-ticker sector peer stats and store in sector_peer_snapshots.

For each sector, computes avg(abs(pct_change_1d)) per ticker from earnings
reactions, then derives the sector-wide aggregate from those per-ticker values.
Both are stored on every row so all readers see identical numbers.

CLI
---
    python -m app.scripts.compute_sector_peers
    python -m app.scripts.compute_sector_peers --sector "Information Technology"
    python -m app.scripts.compute_sector_peers --symbols VMRK      # recompute those symbols' sectors, printing each symbol's inputs
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import func, select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.services.price_history_exclusion import not_excluded
from app.models.sector_peer_snapshot import SectorPeerSnapshot
from app.models.ticker import Ticker

COMPUTATION_VERSION = 1
MIN_PEERS = 5


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute per-ticker sector peer stats"
    )
    parser.add_argument("--sector", default=None, help="Single sector (for testing)")
    parser.add_argument("--symbols", default=None, help="comma-separated symbols: recompute their whole sectors (the aggregate needs every peer) and print each symbol's inputs")
    args = parser.parse_args()

    today = date.today()
    wanted = {x.strip().upper() for x in args.symbols.split(",") if x.strip()} if args.symbols else set()

    async with AsyncSessionLocal() as session:
        # 1. Fetch all active tickers with a sector
        q = select(Ticker).where(Ticker.is_active.is_(True), Ticker.sector.isnot(None))
        if args.sector:
            q = q.where(Ticker.sector == args.sector)
        sectors: set[str] | None = None
        if wanted:
            from app.services.price_history_exclusion import excluded_symbols
            sectors = set((await session.execute(select(Ticker.sector).where(Ticker.symbol.in_(wanted), Ticker.sector.isnot(None)))).scalars().all())
            q = q.where(Ticker.sector.in_(sectors))
            excluded = await excluded_symbols(session)
            for sym in sorted(wanted):
                inputs = (await session.execute(text("""SELECT t.sector, t.is_active, count(hr.id), round(avg(abs(hr.pct_change_1d))::numeric, 4), min(hr.event_date), max(hr.event_date)
                    FROM tickers t LEFT JOIN historical_reactions hr ON hr.ticker_id = t.id AND hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL
                    WHERE t.symbol = :s GROUP BY t.sector, t.is_active"""), {"s": sym})).first()
                print(f"  {sym}: " + (f"sector {inputs[0]}, active {inputs[1]}, {inputs[2]} earnings reactions with a 1-day move, mean |move| {inputs[3]}, {inputs[4]} to {inputs[5]}"
                                      if inputs else "no ticker row") + (", on the price-history exclusion list" if sym in excluded else ""))
        tickers = list((await session.execute(q.order_by(Ticker.symbol))).scalars().all())

        if not tickers:
            print("No tickers with sector found.")
            return 0

        # 2. Compute per-ticker avg(abs(pct_change_1d)) and count for earnings
        per_ticker_rows = (await session.execute(
            select(
                Ticker.symbol,
                Ticker.sector,
                func.avg(func.abs(HistoricalReaction.pct_change_1d)).label("avg_abs"),
                func.count(HistoricalReaction.id).label("qcount"),
            )
            .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
            .where(
                Ticker.is_active.is_(True),
                Ticker.sector.isnot(None),
                HistoricalReaction.event_type == EventType.EARNINGS,
                not_excluded(Ticker.symbol),
                HistoricalReaction.pct_change_1d.isnot(None),
            )
            .group_by(Ticker.symbol, Ticker.sector)
        )).all()

        if args.sector:
            per_ticker_rows = [r for r in per_ticker_rows if r.sector == args.sector]
        if sectors is not None:
            per_ticker_rows = [r for r in per_ticker_rows if r.sector in sectors]

        # Build per-ticker map
        ticker_data: dict[str, dict] = {}
        sector_tickers: dict[str, list[str]] = {}
        for r in per_ticker_rows:
            avg_val = round(float(r.avg_abs), 4) if r.avg_abs is not None else None
            ticker_data[r.symbol] = {
                "sector": r.sector,
                "avg_abs_1d": avg_val,
                "quarter_count": r.qcount,
            }
            sector_tickers.setdefault(r.sector, []).append(r.symbol)

        # 3. Compute sector-wide aggregates from per-ticker values
        sector_aggs: dict[str, dict] = {}
        for sector, symbols in sector_tickers.items():
            peer_avgs = [ticker_data[s]["avg_abs_1d"] for s in symbols
                         if ticker_data[s]["avg_abs_1d"] is not None]
            peer_count = len(peer_avgs)
            if peer_count >= MIN_PEERS:
                sector_avg = round(sum(peer_avgs) / peer_count, 4)
            else:
                sector_avg = None
            sector_aggs[sector] = {
                "sector_avg_abs_1d": sector_avg,
                "sector_peer_count": peer_count,
            }

        # 4. Include tickers with a sector but no reactions (zero values)
        all_symbols_with_sector = {t.symbol: t.sector for t in tickers}
        for sym, sector in all_symbols_with_sector.items():
            if sym not in ticker_data:
                ticker_data[sym] = {
                    "sector": sector,
                    "avg_abs_1d": None,
                    "quarter_count": 0,
                }
                sector_tickers.setdefault(sector, [])

        # 5. Upsert all rows
        upserted = 0
        for sym, data in ticker_data.items():
            sector = data["sector"]
            agg = sector_aggs.get(sector, {"sector_avg_abs_1d": None, "sector_peer_count": 0})

            stmt = sa.text("""
                INSERT INTO sector_peer_snapshots
                    (id, sector, symbol, avg_abs_1d, quarter_count,
                     sector_avg_abs_1d, sector_peer_count, as_of_date,
                     computation_version, created_at)
                VALUES
                    (gen_random_uuid(), :sector, :symbol, :avg_abs_1d, :quarter_count,
                     :sector_avg_abs_1d, :sector_peer_count, :as_of_date,
                     :version, :now)
                ON CONFLICT (symbol, as_of_date) DO UPDATE SET
                    sector = :sector,
                    avg_abs_1d = :avg_abs_1d,
                    quarter_count = :quarter_count,
                    sector_avg_abs_1d = :sector_avg_abs_1d,
                    sector_peer_count = :sector_peer_count,
                    computation_version = :version,
                    created_at = :now
            """)
            await session.execute(stmt, {
                "sector": sector,
                "symbol": sym,
                "avg_abs_1d": data["avg_abs_1d"],
                "quarter_count": data["quarter_count"],
                "sector_avg_abs_1d": agg["sector_avg_abs_1d"],
                "sector_peer_count": agg["sector_peer_count"],
                "as_of_date": today,
                "version": COMPUTATION_VERSION,
                "now": datetime.now(timezone.utc),
            })
            upserted += 1

        await session.commit()
        for sym in sorted(wanted):
            print(f"  {sym} stored for {today}: {ticker_data.get(sym)}")

    sectors_computed = len(sector_aggs)
    print(f"Upserted {upserted} ticker rows across {sectors_computed} sectors.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
