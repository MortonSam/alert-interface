"""Seed stock-split dates from yfinance into the events table.

For each ticker, fetches split info from yfinance's Ticker.info and .splits,
and upserts into events with event_type=SPLIT.

CLI
---
    python -m app.scripts.seed_splits
    python -m app.scripts.seed_splits --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta

import yfinance as yf
from sqlalchemy import select
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker

BATCH_SIZE = 5
BATCH_SLEEP = 2.0
RETRY_DELAYS = (3, 8, 15)
MAX_RATIO_SIDE = 50  # each side of the ratio must be <= this


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_real_split_ratio(ratio_str: str) -> bool:
    """Return True only if ratio looks like a real stock split (both sides <= MAX_RATIO_SIDE)."""
    try:
        parts = ratio_str.split(":")
        if len(parts) != 2:
            return False
        a, b = int(parts[0]), int(parts[1])
        return a >= 1 and b >= 1 and a <= MAX_RATIO_SIDE and b <= MAX_RATIO_SIDE
    except (ValueError, TypeError):
        return False


# ── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_split_info_sync(symbol: str) -> dict | None:
    """Fetch upcoming/recent stock split info from yfinance.
    Returns dict with keys: split_date, split_ratio, or None if unavailable."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
    except Exception:
        return None

    cutoff = date.today() - timedelta(days=30)

    # Check .info for lastSplitDate and lastSplitFactor
    split_ts = info.get("lastSplitDate")
    split_factor = info.get("lastSplitFactor")
    if split_ts is not None and split_factor:
        try:
            split_date = datetime.utcfromtimestamp(split_ts).date()
        except (TypeError, ValueError, OSError):
            split_date = None

        if split_date is not None and split_date >= cutoff:
            ratio_str = str(split_factor)
            if not _is_real_split_ratio(ratio_str):
                tqdm.write(f"  ⊘ {symbol}: skipped non-split adjustment factor {ratio_str}")
                return None
            return {"split_date": split_date, "split_ratio": ratio_str}

    # Also check .splits Series for any entries within window
    try:
        splits = ticker.splits
        if splits is not None and not splits.empty:
            for ts, ratio in splits.items():
                try:
                    split_date = ts.date()
                except AttributeError:
                    continue
                if split_date >= cutoff:
                    # Format ratio: e.g. 4.0 → "4:1"
                    ratio_str = f"{int(ratio)}:1" if ratio == int(ratio) else str(ratio)
                    if not _is_real_split_ratio(ratio_str):
                        tqdm.write(f"  ⊘ {symbol}: skipped non-split adjustment factor {ratio_str}")
                        return None
                    return {"split_date": split_date, "split_ratio": ratio_str}
    except Exception:
        pass

    return None


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_split_event(
    session,
    ticker: Ticker,
    split_date: date,
    split_ratio: str,
) -> bool:
    """Insert split event if not already present. Returns True if inserted."""
    existing = await session.scalar(
        select(Event.id).where(
            Event.ticker_id == ticker.id,
            Event.event_date == split_date,
            Event.event_type == EventType.SPLIT,
        )
    )
    if existing is not None:
        return False

    event = Event(
        ticker_id=ticker.id,
        event_type=EventType.SPLIT,
        event_date=split_date,
        title=f"{ticker.symbol} {split_ratio} Stock Split",
        source=DataSource.YFINANCE,
        is_confirmed=True,
        metadata_={"split_ratio": split_ratio},
    )
    session.add(event)
    return True


# ── Per-ticker bulk processing ───────────────────────────────────────────────

async def _process_ticker(ticker: Ticker, loop) -> tuple[bool, bool]:
    """Fetch + upsert with retries. Returns (ok, inserted)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            info = await loop.run_in_executor(
                None, _fetch_split_info_sync, ticker.symbol
            )
            if info is None:
                return True, False  # ok but no split data

            async with AsyncSessionLocal() as session:
                inserted = await _upsert_split_event(
                    session, ticker, info["split_date"], info["split_ratio"]
                )
                await session.commit()
            return True, inserted
        except Exception as exc:
            last_exc = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)

    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, False


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed stock-split dates from yfinance")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap the candidate list at N (for testing)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )

    candidates = all_tickers
    if args.limit is not None:
        candidates = candidates[:args.limit]
        print(f"--limit {args.limit}: processing first {len(candidates)} tickers.", flush=True)

    if not candidates:
        print("No tickers in database.")
        return 0

    loop = asyncio.get_event_loop()
    succeeded = 0
    inserted_count = 0
    failed_list: list[str] = []

    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]

    with tqdm(total=len(candidates), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [_process_ticker(t, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, inserted) in zip(batch, results):
                if ok:
                    succeeded += 1
                    if inserted:
                        inserted_count += 1
                else:
                    failed_list.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=succeeded, new=inserted_count, fail=len(failed_list))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)

    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {succeeded} tickers processed  📊 {inserted_count} split events inserted  ✗ {len(failed_list)} failed")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 50}")
    return 1 if failed_list else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
