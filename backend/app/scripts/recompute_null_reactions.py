"""Recompute NULL-pct v3 earnings reactions from stored event_date + timing.

Finds every historical_reactions row where:
  - event_type = 'earnings'
  - computation_version = 3
  - pct_change_1d IS NULL
  - event_date is inside the 5-year lookback window

For each, looks up the earnings_report_timing row to get bmo/amc/unknown,
fetches price history from yfinance, and runs _compute_v3.  Rows with
timing=unknown or guard rejections stay NULL.

Usage:
    python -m app.scripts.recompute_null_reactions              # dry run
    python -m app.scripts.recompute_null_reactions --write      # persist
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal

import yfinance as yf
from sqlalchemy import select, text, update

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.seed_historical_reactions import (
    COMPUTATION_VERSION,
    LOOKBACK_YEARS,
    _build_date_cache,
    _compute_v3,
    load_reference_sessions,
    _fetch_price_history,
)

FETCH_TIMEOUT = 30  # seconds per ticker
DUPLICATE_WINDOW_DAYS = 45  # skip rows with a neighbor within this window


async def _run(write: bool = False) -> int:
    today = date.today()
    lookback = today - timedelta(days=LOOKBACK_YEARS * 366)

    async with AsyncSessionLocal() as session:
        # All v3 earnings rows with NULL pcts inside the lookback window
        rows = (await session.execute(
            select(
                HistoricalReaction.id,
                HistoricalReaction.ticker_id,
                HistoricalReaction.event_date,
                Ticker.symbol,
            )
            .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
            .where(
                HistoricalReaction.event_type == EventType.EARNINGS,
                HistoricalReaction.computation_version == COMPUTATION_VERSION,
                HistoricalReaction.pct_change_1d.is_(None),
                HistoricalReaction.event_date >= lookback,
            )
            .order_by(Ticker.symbol, HistoricalReaction.event_date)
        )).all()

        if not rows:
            print("No NULL-pct v3 rows inside lookback. Nothing to do.")
            return 0

        # Build set of (ticker_id, event_date) that have a neighboring
        # earnings row within DUPLICATE_WINDOW_DAYS — skip until dedupe.
        dup_rows = (await session.execute(text(
            "SELECT hr1.ticker_id, hr1.event_date AS d1, hr2.event_date AS d2 "
            "FROM historical_reactions hr1 "
            "JOIN historical_reactions hr2 "
            "  ON hr1.ticker_id = hr2.ticker_id "
            "  AND hr1.event_type = :et AND hr2.event_type = :et "
            "  AND hr2.event_date > hr1.event_date "
            "  AND hr2.event_date - hr1.event_date <= :win "
            "ORDER BY hr1.ticker_id, hr1.event_date"
        ), {"et": "earnings", "win": DUPLICATE_WINDOW_DAYS})).all()
        dup_dates: set[tuple] = set()
        for dr in dup_rows:
            dup_dates.add((dr.ticker_id, dr.d1))
            dup_dates.add((dr.ticker_id, dr.d2))

        print(f"{len(rows)} NULL-pct v3 rows inside lookback (write={write})")
        print(f"{len(dup_dates)} rows in duplicate pairs (skipped until dedupe)\n")

        # Group by ticker for efficient fetching
        by_ticker: dict[str, list] = {}
        for r in rows:
            by_ticker.setdefault(r.symbol, []).append(r)

        # Load all timing data
        timing_rows = (await session.execute(
            select(
                EarningsReportTiming.ticker_id,
                EarningsReportTiming.event_date,
                EarningsReportTiming.timing,
            )
        )).all()
        timing_map: dict[tuple, str] = {
            (r.ticker_id, r.event_date): r.timing for r in timing_rows
        }

        updated = 0
        skipped_unknown = 0
        skipped_no_data = 0
        skipped_guard = 0
        skipped_dup = 0

        for sym, ticker_rows in sorted(by_ticker.items()):
            # Fetch price history once per ticker
            yf_ticker = yf.Ticker(sym)
            try:
                hist = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, _fetch_price_history, yf_ticker, lookback
                    ),
                    timeout=FETCH_TIMEOUT,
                )
            except Exception as exc:
                print(f"  {sym}: price fetch failed — {exc}")
                skipped_no_data += len(ticker_rows)
                continue

            if hist.empty:
                print(f"  {sym}: no price history")
                skipped_no_data += len(ticker_rows)
                continue

            dates_cache = _build_date_cache(hist)

            for r in ticker_rows:
                if (r.ticker_id, r.event_date) in dup_dates:
                    print(f"  {sym}  {r.event_date}  → skip (duplicate pair, pending dedupe)")
                    skipped_dup += 1
                    continue

                timing = timing_map.get((r.ticker_id, r.event_date), "unknown")

                if timing == "unknown":
                    print(f"  {sym}  {r.event_date}  timing=unknown  → skip (correctly NULL)")
                    skipped_unknown += 1
                    continue

                result = _compute_v3(hist, dates_cache, r.event_date, timing, load_reference_sessions())

                if result is None:
                    print(f"  {sym}  {r.event_date}  timing={timing}  → guard rejection")
                    skipped_guard += 1
                    continue

                pct_1d = result["pct_change_1d"]
                pct_3d = result["pct_change_3d"]
                pct_5d = result["pct_change_5d"]

                if pct_1d is None:
                    print(f"  {sym}  {r.event_date}  timing={timing}  → computed NULL (frozen/incomplete)")
                    skipped_guard += 1
                    continue

                print(f"  {sym}  {r.event_date}  timing={timing}  → 1d={pct_1d} 3d={pct_3d} 5d={pct_5d}")

                if write:
                    await session.execute(
                        update(HistoricalReaction)
                        .where(HistoricalReaction.id == r.id)
                        .values(
                            pct_change_1d=pct_1d,
                            pct_change_3d=pct_3d,
                            pct_change_5d=pct_5d,
                            close_before=result["close_before"],
                            open_after=result["open_after"],
                            close_after=result["close_after"],
                            volume_after=result["volume_after"],
                        )
                    )
                    updated += 1

        if write:
            await session.commit()

    print(f"\nSummary: {updated} updated, {skipped_unknown} unknown-timing, "
          f"{skipped_no_data} no-data, {skipped_guard} guard-rejected, "
          f"{skipped_dup} duplicate-skipped")
    return 0


def main() -> int:
    write = "--write" in sys.argv
    return asyncio.run(_run(write=write))


if __name__ == "__main__":
    sys.exit(main())
