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
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.constants import LISTING_DATE_OVERRIDES
from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.historical_reaction import SOURCE_INTRINIO, HistoricalReaction
from app.services import price_bars
from app.models.ticker import Ticker
from app.services.fomc_calendar import FOMC_EVENT_TITLE, ensure_fomc_events, is_decision_day
from app.services.price_history_exclusion import exclusion_list, excluded_symbols
from app.services.step_outcomes import record_step_fields
from app.models.historical_reaction import HistoricalReaction
from app.scripts.seed_historical_reactions import (
    LOOKBACK_YEARS,
    MIN_AGE_DAYS,
    BULK_BATCH_SIZE,
    BULK_BATCH_SLEEP,
    BULK_RETRY_DELAYS,
    FETCH_TIMEOUT,
    _build_date_cache,
    _compute,
    _fetch_price_history,
    load_reference_sessions,
)


# ── FOMC decision dates ──────────────────────────────────────────────────────
# services/fomc_calendar.py holds the official decision days and is the only writer of "FOMC Meeting"
# events. This seeder measures official days only: a stray event row on another day is never seeded.

async def _ensure_fomc_events() -> int:
    """Insert the official decision days into the events table if missing. Returns the count inserted."""
    async with AsyncSessionLocal() as session:
        inserted = await ensure_fomc_events(session)
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
                Event.title == FOMC_EVENT_TITLE,
                Event.event_date >= lookback,
                Event.event_date <= cutoff,
            )
            .order_by(Event.event_date)
        )).all()

    return [(r.event_date, str(r.id)) for r in rows if is_decision_day(r.event_date)]


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_fomc_reaction(
    session,
    ticker: Ticker,
    event_date: date,
    event_id: str | None,
    data: dict,
) -> bool:
    """Upsert on (ticker_id, event_date, event_type=FOMC). Returns True if inserted."""
    data = {**data, "price_source": SOURCE_INTRINIO}
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
            index_elements=["ticker_id", "event_date", "event_type"],
            index_where=text("event_type = 'fomc'"),
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

async def _build_fomc_skip_set(session, fomc_dates: list[date]) -> set[str]:
    """Return symbols that already have a FOMC reaction for every expected date.

    Past FOMC dates are fixed, so a ticker with a row for every processable
    date has nothing new to compute. Dates before a LISTING_DATE_OVERRIDES
    entry are never seeded, so they count as satisfied: only rows and expected
    dates on/after the override are compared.
    """
    rows = (await session.execute(
        select(Ticker.symbol, HistoricalReaction.event_date)
        .join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(HistoricalReaction.event_type == EventType.FOMC)
    )).all()
    have: dict[str, int] = {}
    for sym, d in rows:
        floor = LISTING_DATE_OVERRIDES.get(sym)
        if floor is None or d >= floor:
            have[sym] = have.get(sym, 0) + 1

    skip: set[str] = set()
    for sym, n in have.items():
        floor = LISTING_DATE_OVERRIDES.get(sym)
        expected = sum(1 for d in fomc_dates if floor is None or d >= floor)
        if n >= expected:
            skip.add(sym)
    return skip


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
        if sym in await excluded_symbols(session):
            print(f"  ⚠  {sym} is excluded: its price history failed the RV guard (data_error). Nothing seeded.")
            return

    fomc_dates = await _load_fomc_dates()
    if not fomc_dates:
        print("  ⚠  No FOMC meeting dates found in events table")
        return
    print(f"  Found {len(fomc_dates)} FOMC dates in lookback window")

    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)

    print("  Loading stored price bars...")
    try:
        hist = _fetch_price_history(sym, lookback)
    except Exception as exc:
        print(f"  ERROR: price history failed — {exc}")
        return

    if hist.empty:
        print("  ⚠  No price history returned")
        return

    dates_cache = _build_date_cache(hist)

    floor_date = LISTING_DATE_OVERRIDES.get(sym)

    inserted = updated = skipped = 0
    async with AsyncSessionLocal() as session:
        kept = await price_bars.stored_history_dates(session, sym, [d for d, _ in fomc_dates], load_reference_sessions())
        await price_bars.mark_stored_history(session, ticker.id, EventType.FOMC, kept)
        for event_date, event_id in fomc_dates:
            if (floor_date and event_date < floor_date) or event_date in kept:
                skipped += 1
                continue
            data = _compute(hist, dates_cache, event_date, load_reference_sessions())
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
    """The stored shadow bars for the seeder's window (services/price_bars) — called via run_in_executor."""
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    return _fetch_price_history(symbol, lookback)


FOMC_STEP_LABEL = "FOMC reactions"       # the label in refresh.STEPS
FOMC_FETCH_TIMEOUT = 30                  # per-ticker price fetch; a stalled ticker is skipped, not retried
TIME_BUDGET_SECONDS = 600                # the step finishes inside its 900s timeout whatever yfinance does


class PriceFetchStalled(Exception):
    """The ticker's price fetch exceeded FOMC_FETCH_TIMEOUT."""


def nothing_new(newest_fomc: date | None, newest_reaction: date | None, unseeded: int) -> bool:
    """Skip the run when no FOMC date in the window is newer than the newest stored reaction
    and every active ticker already has its full set."""
    if newest_fomc is None:
        return True
    return newest_reaction is not None and newest_fomc <= newest_reaction and unseeded == 0


async def _seed_ticker_bulk(
    ticker: Ticker,
    fomc_dates: list[tuple[date, str]],
    loop,
    floor_date: date | None = None,
) -> tuple[int, int, int]:
    """Seed one ticker in bulk mode. Returns (inserted, updated, no_price_data)."""
    try:
        hist = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_price_sync, ticker.symbol),
            timeout=FOMC_FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise PriceFetchStalled(f"price fetch exceeded {FOMC_FETCH_TIMEOUT}s")
    if hist.empty:
        return 0, 0, 0

    dates_cache = _build_date_cache(hist)
    inserted = updated = no_price = 0

    async with AsyncSessionLocal() as session:
        kept = await price_bars.stored_history_dates(session, ticker.symbol, [d for d, _ in fomc_dates], load_reference_sessions())
        await price_bars.mark_stored_history(session, ticker.id, EventType.FOMC, kept)
        for event_date, event_id in fomc_dates:
            if (floor_date and event_date < floor_date) or event_date in kept:
                no_price += 1           # before listing, or on a stored_history span: kept as stored
                continue
            data = _compute(hist, dates_cache, event_date, load_reference_sessions())
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
    floor_date: date | None = None,
) -> tuple[bool, int, int, int, str | None]:
    """Fetch + upsert with retries. Returns (ok, inserted, updated, no_price, skip_reason).

    A stalled price fetch is skipped at once with its reason (retrying a stall
    is what turned a 64s step into a 900s timeout); other errors retry.
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate(BULK_RETRY_DELAYS, start=1):
        try:
            ins, upd, nop = await _seed_ticker_bulk(ticker, fomc_dates, loop, floor_date)
            return True, ins, upd, nop, None
        except PriceFetchStalled as exc:
            tqdm.write(f"  ⏱ {ticker.symbol}: skipped, {exc}")
            return False, 0, 0, 0, str(exc)
        except Exception as exc:
            last_exc = exc
            if attempt < len(BULK_RETRY_DELAYS):
                await asyncio.sleep(delay)
    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(BULK_RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0, 0, 0, f"failed after {len(BULK_RETRY_DELAYS)} attempts: {last_exc}"


# ── Bulk main ────────────────────────────────────────────────────────────────

async def main_bulk(limit: int | None) -> int:
    # 1. Load FOMC dates
    fomc_dates = await _load_fomc_dates()
    if not fomc_dates:
        print("No FOMC meeting dates found in events table. Run seed_macro first.")
        return 1

    print(f"Found {len(fomc_dates)} FOMC dates in lookback window.", flush=True)

    # 2. Load all active DB tickers, less those whose price history the RV guard rejected
    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )
        excluded = await exclusion_list(session, "FOMC reactions")

    candidates = [t for t in all_tickers if t.symbol not in excluded]
    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 3. Build skip set — skip tickers that already have all expected dates
    expected = len(fomc_dates)
    async with AsyncSessionLocal() as session:
        skip_set = await _build_fomc_skip_set(session, [d for d, _ in fomc_dates])

    to_process = [t for t in candidates if t.symbol not in skip_set]
    n_skipped = len(candidates) - len(to_process)
    if n_skipped:
        print(
            f"{n_skipped} skipped (already have all {expected} FOMC reactions, less pre-listing dates).",
            flush=True,
        )

    # Skip fast: nothing newer than the newest stored reaction and every ticker complete
    newest_fomc = max((d for d, _ in fomc_dates), default=None)
    async with AsyncSessionLocal() as session:
        newest_reaction = await session.scalar(
            select(func.max(HistoricalReaction.event_date)).where(HistoricalReaction.event_type == EventType.FOMC)
        )
    if nothing_new(newest_fomc, newest_reaction, len(to_process)):
        msg = (f"nothing new: newest FOMC date {newest_fomc}, newest stored reaction {newest_reaction}, "
               f"{len(candidates)} tickers complete")
        print(msg, flush=True)
        await record_step_fields(FOMC_STEP_LABEL, {"nothing_new": True, "note": msg, "skipped": []})
        return 0
    if not to_process:
        print("Nothing to process.")
        await record_step_fields(FOMC_STEP_LABEL, {"nothing_new": False, "note": "no tickers to process", "skipped": []})
        return 0

    # 4. Process in batches, inside a time budget
    loop = asyncio.get_event_loop()
    started = time.monotonic()
    succeeded: list[str] = []
    failed: list[str] = []
    skipped: list[dict] = []      # {symbol, reason}
    total_ins = total_upd = total_nop = 0

    batches = [to_process[i:i + BULK_BATCH_SIZE] for i in range(0, len(to_process), BULK_BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            if time.monotonic() - started > TIME_BUDGET_SECONDS:
                rest = [t.symbol for b in batches[batch_idx:] for t in b]
                for sym in rest:
                    skipped.append({"symbol": sym, "reason": f"not reached: time budget of {TIME_BUDGET_SECONDS}s"})
                print(f"  Time budget reached; {len(rest)} ticker(s) wait for the next run", flush=True)
                break
            tasks = [
                _process_ticker_bulk(t, fomc_dates, loop, LISTING_DATE_OVERRIDES.get(t.symbol))
                for t in batch
            ]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, ins, upd, nop, reason) in zip(batch, results):
                if ok:
                    succeeded.append(ticker.symbol)
                    total_ins += ins
                    total_upd += upd
                    total_nop += nop
                elif reason and reason.startswith("price fetch exceeded"):
                    skipped.append({"symbol": ticker.symbol, "reason": reason})
                else:
                    failed.append(ticker.symbol)
                    skipped.append({"symbol": ticker.symbol, "reason": reason or "failed"})
                bar.update(1)
                bar.set_postfix(ok=len(succeeded), skip=n_skipped, fail=len(failed))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BULK_BATCH_SLEEP)

    # 5. Summary
    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {len(succeeded)} succeeded  ⚠ {n_skipped} already complete  ⏱ {len(skipped)} skipped  ✗ {len(failed)} failed")
    print(f"  📊 {total_ins} inserted  {total_upd} updated  {total_nop} no-price-data")
    if skipped:
        print("\n  Skipped: " + ", ".join(f"{d['symbol']} ({d['reason']})" for d in skipped[:20]))
    print(f"{'─' * 50}")
    await record_step_fields(FOMC_STEP_LABEL, {
        "nothing_new": False, "succeeded": len(succeeded), "already_complete": n_skipped,
        "failed": len(failed), "skipped": skipped[:50], "seconds": round(time.monotonic() - started, 1),
    })
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
