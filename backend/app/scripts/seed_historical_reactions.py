"""Seed historical earnings reactions from yfinance.

For each past earnings date (up to 5 years back) we pull daily price history
and compute price moves relative to the open on the event day:

  open_after   : open price on event day T  (the baseline)
  close_after  : close price on event day T
  close_before : close price on the last trading day before T
  pct_change_1d: (close on first trading day >= T+1 - open_T) / open_T * 100
  pct_change_3d: (close on first trading day >= T+3 - open_T) / open_T * 100
  pct_change_5d: (close on first trading day >= T+5 - open_T) / open_T * 100
  volume_after : volume on event day T

"T+N" counts calendar days from event_date and rolls forward to the next
trading day when the target falls on a weekend or market holiday.

Upserts match on (ticker_id, event_date, event_type).

CLI flags
---------
  TICKER [...]   Seed specific ticker(s) — one-off mode (unchanged)
  --all          Process every ticker in the database
  --retry-only   Only retry symbols from cache/failed_reactions.json
  --limit N      Cap the candidate list at N (for testing)

Usage
-----
    python -m app.scripts.seed_historical_reactions AAPL
    python -m app.scripts.seed_historical_reactions AAPL MSFT NVDA
    python -m app.scripts.seed_historical_reactions --all
    python -m app.scripts.seed_historical_reactions --all --limit 20
    python -m app.scripts.seed_historical_reactions --retry-only
    make seed-reactions TICKER=AAPL
    make seed-reactions-all
    make seed-reactions-retry
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models.enums import EarningsOutcome, EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker


LOOKBACK_YEARS = 5
# We need T+5 data, so skip very recent earnings to avoid incomplete windows
MIN_AGE_DAYS = 8

# ── Paths ─────────────────────────────────────────────────────────────────────

CACHE_DIR              = Path(__file__).parent / "cache"
FAILED_REACTIONS_CACHE = CACHE_DIR / "failed_reactions.json"

# ── Bulk-run tuning ───────────────────────────────────────────────────────────

BULK_BATCH_SIZE    = 5
BULK_BATCH_SLEEP   = 3.0          # seconds between batches
BULK_RETRY_DELAYS  = (3, 8, 15)   # seconds for retry 1, 2, 3
SKIP_MIN_REACTIONS = 15           # skip if ticker already has at least this many ...
SKIP_WITHIN_DAYS   = 14           # ... AND the most recent is within this many days


# ── Price helpers ─────────────────────────────────────────────────────────────

def _build_date_cache(hist: pd.DataFrame) -> np.ndarray:
    """Return numpy array of Python date objects parallel to hist rows."""
    return hist.index.map(lambda ts: ts.date()).values


def _close_on_or_after(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on the first trading day on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.argmax(mask))])


def _resolved_date_on_or_after(dates: np.ndarray, target: date) -> date | None:
    """Return the actual trading date that is on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    return dates[int(np.argmax(mask))]


def _close_on_date(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on an exact date (must be a trading day)."""
    mask = dates == target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.argmax(mask))])


def _open_vol_on_or_after(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> tuple[float, int] | None:
    """(open, volume) on the first trading day on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    idx = int(np.argmax(mask))
    return float(hist["Open"].iloc[idx]), int(hist["Volume"].iloc[idx])


def _close_strictly_before(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on the last trading day strictly before target."""
    mask = dates < target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.sum(mask)) - 1])


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _compute_outcome(
    eps_estimate: Decimal | None, eps_actual: Decimal | None
) -> EarningsOutcome:
    if eps_estimate is None or eps_actual is None:
        return EarningsOutcome.UNKNOWN
    diff = eps_actual - eps_estimate
    if abs(diff) <= Decimal("0.01"):
        return EarningsOutcome.MEET
    return EarningsOutcome.BEAT if diff > 0 else EarningsOutcome.MISS


def _fetch_earnings_dates(t: yf.Ticker) -> list[tuple[date, Decimal | None, Decimal | None]]:
    """Return list of (event_date, eps_estimate, eps_actual) within the lookback window, oldest first."""
    today = date.today()
    lookback = today - timedelta(days=LOOKBACK_YEARS * 366)
    cutoff = today - timedelta(days=MIN_AGE_DAYS)

    try:
        df = t.earnings_dates
    except Exception as exc:
        print(f"    ⚠  earnings_dates error: {exc}")
        return []

    if df is None or df.empty:
        return []

    results: list[tuple[date, Decimal | None, Decimal | None]] = []
    for ts, row in df.iterrows():
        try:
            d = ts.date() if hasattr(ts, "date") else None
        except Exception:
            continue
        if not (d and lookback <= d <= cutoff):
            continue

        def _to_dec(val) -> Decimal | None:
            try:
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    return None
                return Decimal(str(round(float(val), 4)))
            except Exception:
                return None

        eps_est = _to_dec(row.get("EPS Estimate"))
        eps_act = _to_dec(row.get("Reported EPS"))
        results.append((d, eps_est, eps_act))

    return sorted(results, key=lambda x: x[0])


def _fetch_price_history(t: yf.Ticker, lookback: date) -> pd.DataFrame:
    """Fetch daily OHLCV from lookback-30d to today+2d for roll-forward buffer."""
    start = (lookback - timedelta(days=30)).isoformat()
    end   = (date.today() + timedelta(days=2)).isoformat()
    hist = t.history(start=start, end=end, auto_adjust=True)
    return hist.sort_index()


# ── Reaction computation ──────────────────────────────────────────────────────

def _compute(
    hist: pd.DataFrame,
    dates: np.ndarray,
    event_date: date,
) -> dict | None:
    ov = _open_vol_on_or_after(hist, dates, event_date)
    if ov is None:
        return None
    open_t, vol_t = ov
    if open_t == 0:
        return None

    actual_t_date = dates[int(np.argmax(dates >= event_date))]

    def d2(v: float | None) -> Decimal | None:
        return Decimal(str(round(v, 4))) if v is not None else None

    def pct(close: float | None) -> Decimal | None:
        if close is None:
            return None
        return Decimal(str(round((close - open_t) / open_t * 100, 4)))

    close_t      = _close_on_or_after(hist, dates, event_date)
    close_before = _close_strictly_before(hist, dates, actual_t_date)

    # Resolve T+1 and T+3 normally: first trading day on or after the calendar target.
    t1_date = _resolved_date_on_or_after(dates, event_date + timedelta(days=1))
    t3_date = _resolved_date_on_or_after(dates, event_date + timedelta(days=3))

    # T+5: roll forward to the first trading day on or after (event_date + 5), BUT
    # it must be strictly later than T+3's resolved date.  Without this guard,
    # Wednesday earnings collapse T+3 and T+5 onto the same Monday
    # (Sat→Mon for +3 and Mon→Mon for +5).
    t5_calendar = event_date + timedelta(days=5)
    if t3_date is not None:
        t5_calendar = max(t5_calendar, t3_date + timedelta(days=1))
    t5_date = _resolved_date_on_or_after(dates, t5_calendar)

    close_t1 = _close_on_date(hist, dates, t1_date) if t1_date else None
    close_t3 = _close_on_date(hist, dates, t3_date) if t3_date else None
    close_t5 = _close_on_date(hist, dates, t5_date) if t5_date else None

    return dict(
        close_before  = d2(close_before),
        open_after    = d2(open_t),
        close_after   = d2(close_t),
        pct_change_1d = pct(close_t1),
        pct_change_3d = pct(close_t3),
        pct_change_5d = pct(close_t5),
        volume_after  = vol_t,
    )


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_reaction(
    session,
    ticker: Ticker,
    event_date: date,
    data: dict,
) -> bool:
    """Upsert on (ticker_id, event_date, event_type). Returns True if inserted."""
    stmt = (
        pg_insert(HistoricalReaction)
        .values(
            ticker_id  = ticker.id,
            event_type = EventType.EARNINGS,
            event_date = event_date,
            **data,
        )
        .on_conflict_do_update(
            constraint = "uq_hist_reaction_ticker_date_type",
            set_       = data,
        )
        .returning(HistoricalReaction.id)
    )
    # pg_insert returns a scalar — we can't easily tell insert vs update here,
    # so we check for pre-existence first.
    existing = await session.scalar(
        select(HistoricalReaction.id).where(
            HistoricalReaction.ticker_id  == ticker.id,
            HistoricalReaction.event_date == event_date,
            HistoricalReaction.event_type == EventType.EARNINGS,
        )
    )
    await session.execute(stmt)
    return existing is None


# ── Failed-ticker cache ───────────────────────────────────────────────────────

def load_failed_reactions() -> list[str]:
    if not FAILED_REACTIONS_CACHE.exists():
        return []
    return json.loads(FAILED_REACTIONS_CACHE.read_text())


def save_failed_reactions(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_REACTIONS_CACHE.write_text(json.dumps(sorted(symbols), indent=2))


# ── Skip logic ────────────────────────────────────────────────────────────────

async def build_reactions_skip_set(session) -> set[str]:
    """Return symbols that already have >= SKIP_MIN_REACTIONS reactions within SKIP_WITHIN_DAYS."""
    cutoff = date.today() - timedelta(days=SKIP_WITHIN_DAYS)
    rows = (await session.execute(
        select(Ticker.symbol)
        .join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(HistoricalReaction.event_type == EventType.EARNINGS)
        .group_by(Ticker.id, Ticker.symbol)
        .having(
            func.count(HistoricalReaction.id) >= SKIP_MIN_REACTIONS,
            func.max(HistoricalReaction.event_date) >= cutoff,
        )
    )).scalars().all()
    return set(rows)


# ── Per-ticker seed (one-off, verbose) ────────────────────────────────────────

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

    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    yf_ticker = yf.Ticker(sym)

    print("  Fetching earnings dates...")
    earnings_entries = _fetch_earnings_dates(yf_ticker)
    if not earnings_entries:
        print("  ⚠  No past earnings dates found in 5-year window")
        return
    print(f"  Found {len(earnings_entries)} past earnings dates")

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
        for event_date, eps_estimate, eps_actual in earnings_entries:
            data = _compute(hist, dates_cache, event_date)
            if data is None:
                skipped += 1
                continue
            data["eps_estimate"] = eps_estimate
            data["eps_actual"]   = eps_actual
            data["outcome"]      = _compute_outcome(eps_estimate, eps_actual)
            created = await upsert_reaction(session, ticker, event_date, data)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    print(f"  ✓ {inserted} inserted, {updated} updated, {skipped} skipped")


# ── Bulk infrastructure ───────────────────────────────────────────────────────

def _fetch_ticker_data_sync(symbol: str) -> tuple[list, pd.DataFrame]:
    """Sync yfinance fetch — called via run_in_executor.
    Returns (earnings_entries, hist_df); raises on hard failure."""
    yf_ticker = yf.Ticker(symbol)
    earnings_entries = _fetch_earnings_dates(yf_ticker)
    if not earnings_entries:
        return [], pd.DataFrame()
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    hist = _fetch_price_history(yf_ticker, lookback)
    return earnings_entries, hist


async def _seed_ticker_bulk(ticker: Ticker, loop) -> tuple[int, int, int]:
    """Seed one ticker in bulk mode. Returns (inserted, updated, no_price_data).
    Raises on any error so the retry wrapper can catch it."""
    earnings_entries, hist = await loop.run_in_executor(
        None, _fetch_ticker_data_sync, ticker.symbol
    )
    if not earnings_entries or hist.empty:
        return 0, 0, 0

    dates_cache = _build_date_cache(hist)
    inserted = updated = no_price = 0

    async with AsyncSessionLocal() as session:
        for event_date, eps_estimate, eps_actual in earnings_entries:
            data = _compute(hist, dates_cache, event_date)
            if data is None:
                no_price += 1
                continue
            data["eps_estimate"] = eps_estimate
            data["eps_actual"]   = eps_actual
            data["outcome"]      = _compute_outcome(eps_estimate, eps_actual)
            created = await upsert_reaction(session, ticker, event_date, data)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    return inserted, updated, no_price


async def process_ticker_bulk(ticker: Ticker, loop) -> tuple[bool, int, int, int]:
    """Fetch + upsert with retries. Returns (ok, inserted, updated, no_price)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(BULK_RETRY_DELAYS, start=1):
        try:
            ins, upd, nop = await _seed_ticker_bulk(ticker, loop)
            return True, ins, upd, nop
        except Exception as exc:
            last_exc = exc
            if attempt < len(BULK_RETRY_DELAYS):
                await asyncio.sleep(delay)
    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(BULK_RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0, 0, 0


# ── Bulk main ─────────────────────────────────────────────────────────────────

async def main_bulk(retry_only: bool, limit: int | None, force: bool = False) -> int:
    # 1. Load all DB tickers
    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(select(Ticker).order_by(Ticker.symbol))).scalars().all()
        )

    by_symbol = {t.symbol: t for t in all_tickers}

    if retry_only:
        failed_symbols = load_failed_reactions()
        if not failed_symbols:
            print("No failed tickers in cache. Nothing to retry.")
            return 0
        candidates = [by_symbol[s] for s in failed_symbols if s in by_symbol]
        print(f"Retrying {len(candidates)} previously-failed tickers.", flush=True)
    else:
        candidates = all_tickers

    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 2. Build skip set (empty when --force)
    if force:
        skip_set: set[str] = set()
        print("--force: skipping freshness check, reprocessing all tickers.", flush=True)
    else:
        async with AsyncSessionLocal() as session:
            skip_set = await build_reactions_skip_set(session)

    to_process = [t for t in candidates if t.symbol not in skip_set]
    n_skipped  = len(candidates) - len(to_process)
    if n_skipped:
        print(
            f"{n_skipped} skipped "
            f"(≥{SKIP_MIN_REACTIONS} reactions within {SKIP_WITHIN_DAYS} days).",
            flush=True,
        )

    if not to_process:
        print("Nothing to process.")
        return 0

    # 3. Process in batches
    loop = asyncio.get_event_loop()
    succeeded: list[str] = []
    failed:    list[str] = []
    total_ins = total_upd = total_nop = 0

    batches = [to_process[i : i + BULK_BATCH_SIZE] for i in range(0, len(to_process), BULK_BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [process_ticker_bulk(t, loop) for t in batch]
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

    # 4. Persist failures
    if retry_only:
        still_failed = [s for s in load_failed_reactions() if s not in succeeded]
        save_failed_reactions(still_failed)
    else:
        existing_failed = load_failed_reactions()
        merged_failed   = sorted(set(existing_failed) | set(failed) - set(succeeded))
        save_failed_reactions(merged_failed)

    # 5. Summary
    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {len(succeeded)} succeeded  ⚠ {n_skipped} skipped  ✗ {len(failed)} failed")
    print(f"  📊 {total_ins} inserted  {total_upd} updated  {total_nop} no-price-data")
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")
        print("  Run `make seed-reactions-retry` to retry just those.")
    print(f"{'─' * 50}")
    return 1 if failed else 0


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed historical earnings reactions")
    p.add_argument("tickers", nargs="*", metavar="TICKER",
                   help="Specific ticker(s) to seed (one-off mode)")
    p.add_argument("--all", action="store_true", dest="all_tickers",
                   help="Process every ticker in the database")
    p.add_argument("--retry-only", action="store_true",
                   help="Only retry symbols from cache/failed_reactions.json")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Cap the candidate list at N (for testing; use with --all or --retry-only)")
    p.add_argument("--force", action="store_true",
                   help="Skip the freshness check and reprocess all tickers")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    if args.all_tickers or args.retry_only:
        return await main_bulk(retry_only=args.retry_only, limit=args.limit, force=args.force)

    # One-off mode: positional TICKER args
    symbols = [s.upper() for s in args.tickers]
    if not symbols:
        print("Usage: python -m app.scripts.seed_historical_reactions SYMBOL [SYMBOL ...]")
        print("       python -m app.scripts.seed_historical_reactions --all [--limit N]")
        print("       python -m app.scripts.seed_historical_reactions --retry-only")
        return 1

    for sym in symbols:
        await seed(sym)
    print("\n✓ Done.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
