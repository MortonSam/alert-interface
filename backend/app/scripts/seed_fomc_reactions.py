"""Seed per-ticker price reactions to FOMC meetings.

Mirrors seed_historical_reactions.py but sources event dates from the events
table (FOMC meetings seeded by seed_macro.py) instead of yfinance earnings.

For each past FOMC date we compute the same price reaction metrics:
  open_after, close_after, close_before, pct_change_1d/3d/5d, volume_after

No EPS/revenue/outcome fields — those are left as NULL/UNKNOWN defaults.

Upserts match on (ticker_id, event_date, event_type='fomc').

CLI
---
    python -m app.scripts.seed_fomc_reactions          # all tickers
    python -m app.scripts.seed_fomc_reactions AAPL      # single ticker
    python -m app.scripts.seed_fomc_reactions --limit 5 # testing
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.seed_historical_reactions import (
    LOOKBACK_YEARS,
    MIN_AGE_DAYS,
    BULK_BATCH_SIZE,
    BULK_BATCH_SLEEP,
    BULK_RETRY_DELAYS,
    SKIP_MIN_REACTIONS,
    SKIP_WITHIN_DAYS,
    _build_date_cache,
    _compute,
    _fetch_price_history,
)


# ── Historical FOMC decision dates ───────────────────────────────────────────
# Second day (decision day) of each scheduled FOMC meeting, Jan 2021 – present.
# Source: Federal Reserve Board public calendar.

FOMC_DECISION_DATES: list[date] = [
    # 2021
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28),
    date(2021, 6, 16), date(2021, 7, 28), date(2021, 9, 22),
    date(2021, 11, 3), date(2021, 12, 15),
    # 2022
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4),
    date(2022, 6, 15), date(2022, 7, 27), date(2022, 9, 21),
    date(2022, 11, 2), date(2022, 12, 14),
    # 2023
    date(2023, 2, 1),  date(2023, 3, 22), date(2023, 5, 3),
    date(2023, 6, 14), date(2023, 7, 26), date(2023, 9, 20),
    date(2023, 11, 1), date(2023, 12, 13),
    # 2024
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1),
    date(2024, 6, 12), date(2024, 7, 31), date(2024, 9, 18),
    date(2024, 11, 7), date(2024, 12, 18),
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 17),
    # 2026 (through present)
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17),
]


# ── Ensure FOMC events exist in DB ──────────────────────────────────────────

async def _ensure_fomc_events() -> int:
    """Insert historical FOMC dates into events table if missing.
    Matches the existing pattern: event_type='macro', title='FOMC Meeting', source='fred'.
    Returns count of newly inserted rows."""
    inserted = 0
    async with AsyncSessionLocal() as session:
        for d in FOMC_DECISION_DATES:
            existing = await session.scalar(
                select(Event.id).where(
                    Event.event_type == EventType.MACRO,
                    Event.title == "FOMC Meeting",
                    Event.event_date == d,
                )
            )
            if existing is not None:
                continue
            session.add(Event(
                ticker_id=None,
                event_type=EventType.MACRO,
                event_date=d,
                title="FOMC Meeting",
                source=DataSource.FRED,
                is_confirmed=True,
                metadata_={},
            ))
            inserted += 1
        await session.commit()
    return inserted


# ── FOMC dates from DB ──────────────────────────────────────────────────────

async def _load_fomc_dates() -> list[tuple[date, str]]:
    """Ensure historical FOMC events exist, then return (event_date, event_id) pairs
    for FOMC meetings within the lookback window."""
    backfilled = await _ensure_fomc_events()
    if backfilled:
        print(f"  Backfilled {backfilled} historical FOMC meeting events.", flush=True)

    today = date.today()
    lookback = today - timedelta(days=LOOKBACK_YEARS * 366)
    cutoff = today - timedelta(days=MIN_AGE_DAYS)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Event.event_date, Event.id)
            .where(
                Event.event_type == EventType.MACRO,
                Event.title == "FOMC Meeting",
                Event.event_date >= lookback,
                Event.event_date <= cutoff,
            )
            .order_by(Event.event_date)
        )).all()

    return [(r.event_date, str(r.id)) for r in rows]


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_fomc_reaction(
    session,
    ticker: Ticker,
    event_date: date,
    event_id: str | None,
    data: dict,
) -> bool:
    """Upsert on (ticker_id, event_date, event_type=FOMC). Returns True if inserted."""
    values = dict(
        ticker_id=ticker.id,
        event_type=EventType.FOMC,
        event_date=event_date,
        event_id=event_id,
        **data,
    )
    stmt = (
        pg_insert(HistoricalReaction)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_hist_reaction_ticker_date_type",
            set_=data,
        )
    )
    existing = await session.scalar(
        select(HistoricalReaction.id).where(
            HistoricalReaction.ticker_id == ticker.id,
            HistoricalReaction.event_date == event_date,
            HistoricalReaction.event_type == EventType.FOMC,
        )
    )
    await session.execute(stmt)
    return existing is None


# ── Skip logic ───────────────────────────────────────────────────────────────

async def _build_fomc_skip_set(session) -> set[str]:
    """Return symbols that already have >= SKIP_MIN_REACTIONS FOMC reactions within SKIP_WITHIN_DAYS."""
    cutoff = date.today() - timedelta(days=SKIP_WITHIN_DAYS)
    rows = (await session.execute(
        select(Ticker.symbol)
        .join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(HistoricalReaction.event_type == EventType.FOMC)
        .group_by(Ticker.id, Ticker.symbol)
        .having(
            func.count(HistoricalReaction.id) >= SKIP_MIN_REACTIONS,
            func.max(HistoricalReaction.event_date) >= cutoff,
        )
    )).scalars().all()
    return set(rows)


# ── Per-ticker seed (one-off, verbose) ───────────────────────────────────────

async def seed(symbol: str) -> None:
    sym = symbol.upper()
    print(f"\n── {sym} {'─' * (46 - len(sym))}")

    async with AsyncSessionLocal() as session:
        ticker = await session.scalar(
            select(Ticker).where(Ticker.symbol == sym)
        )
        if ticker is None:
            print(f"  ⚠  Not in DB — run `make seed TICKER={sym}` first")
            return

    fomc_dates = await _load_fomc_dates()
    if not fomc_dates:
        print("  ⚠  No FOMC meeting dates found in events table")
        return
    print(f"  Found {len(fomc_dates)} FOMC dates in lookback window")

    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    yf_ticker = yf.Ticker(sym)

    print("  Fetching price history...")
    try:
        hist = _fetch_price_history(yf_ticker, lookback)
    except Exception as exc:
        print(f"  ERROR: price history failed — {exc}")
        return

    if hist.empty:
        print("  ⚠  No price history returned")
        return

    dates_cache = _build_date_cache(hist)

    inserted = updated = skipped = 0
    async with AsyncSessionLocal() as session:
        for event_date, event_id in fomc_dates:
            data = _compute(hist, dates_cache, event_date)
            if data is None:
                skipped += 1
                continue
            created = await _upsert_fomc_reaction(session, ticker, event_date, event_id, data)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    print(f"  ✓ {inserted} inserted, {updated} updated, {skipped} skipped")


# ── Bulk infrastructure ──────────────────────────────────────────────────────

def _fetch_price_sync(symbol: str) -> pd.DataFrame:
    """Sync yfinance fetch — called via run_in_executor."""
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    yf_ticker = yf.Ticker(symbol)
    return _fetch_price_history(yf_ticker, lookback)


async def _seed_ticker_bulk(
    ticker: Ticker,
    fomc_dates: list[tuple[date, str]],
    loop,
) -> tuple[int, int, int]:
    """Seed one ticker in bulk mode. Returns (inserted, updated, no_price_data)."""
    hist = await loop.run_in_executor(None, _fetch_price_sync, ticker.symbol)
    if hist.empty:
        return 0, 0, 0

    dates_cache = _build_date_cache(hist)
    inserted = updated = no_price = 0

    async with AsyncSessionLocal() as session:
        for event_date, event_id in fomc_dates:
            data = _compute(hist, dates_cache, event_date)
            if data is None:
                no_price += 1
                continue
            created = await _upsert_fomc_reaction(session, ticker, event_date, event_id, data)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    return inserted, updated, no_price


async def _process_ticker_bulk(
    ticker: Ticker,
    fomc_dates: list[tuple[date, str]],
    loop,
) -> tuple[bool, int, int, int]:
    """Fetch + upsert with retries. Returns (ok, inserted, updated, no_price)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(BULK_RETRY_DELAYS, start=1):
        try:
            ins, upd, nop = await _seed_ticker_bulk(ticker, fomc_dates, loop)
            return True, ins, upd, nop
        except Exception as exc:
            last_exc = exc
            if attempt < len(BULK_RETRY_DELAYS):
                await asyncio.sleep(delay)
    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(BULK_RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0, 0, 0


# ── Bulk main ────────────────────────────────────────────────────────────────

async def main_bulk(limit: int | None) -> int:
    # 1. Load FOMC dates
    fomc_dates = await _load_fomc_dates()
    if not fomc_dates:
        print("No FOMC meeting dates found in events table. Run seed_macro first.")
        return 1

    print(f"Found {len(fomc_dates)} FOMC dates in lookback window.", flush=True)

    # 2. Load all active DB tickers
    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )

    candidates = all_tickers
    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 3. Build skip set
    async with AsyncSessionLocal() as session:
        skip_set = await _build_fomc_skip_set(session)

    to_process = [t for t in candidates if t.symbol not in skip_set]
    n_skipped = len(candidates) - len(to_process)
    if n_skipped:
        print(
            f"{n_skipped} skipped "
            f"(≥{SKIP_MIN_REACTIONS} FOMC reactions within {SKIP_WITHIN_DAYS} days).",
            flush=True,
        )

    if not to_process:
        print("Nothing to process.")
        return 0

    # 4. Process in batches
    loop = asyncio.get_event_loop()
    succeeded: list[str] = []
    failed: list[str] = []
    total_ins = total_upd = total_nop = 0

    batches = [to_process[i:i + BULK_BATCH_SIZE] for i in range(0, len(to_process), BULK_BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [_process_ticker_bulk(t, fomc_dates, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, ins, upd, nop) in zip(batch, results):
                if ok:
                    succeeded.append(ticker.symbol)
                    total_ins += ins
                    total_upd += upd
                    total_nop += nop
                else:
                    failed.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=len(succeeded), skip=n_skipped, fail=len(failed))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BULK_BATCH_SLEEP)

    # 5. Summary
    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {len(succeeded)} succeeded  ⚠ {n_skipped} skipped  ✗ {len(failed)} failed")
    print(f"  📊 {total_ins} inserted  {total_upd} updated  {total_nop} no-price-data")
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")
    print(f"{'─' * 50}")
    return 1 if failed else 0


# ── Entry point ──────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed per-ticker FOMC price reactions")
    p.add_argument("tickers", nargs="*", metavar="TICKER",
                   help="Specific ticker(s) to seed (one-off mode)")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Cap the candidate list at N (for testing)")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    if args.tickers:
        for sym in args.tickers:
            await seed(sym.upper())
        print("\n✓ Done.\n")
        return 0

    return await main_bulk(limit=args.limit)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
