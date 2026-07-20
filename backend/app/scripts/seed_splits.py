"""Seed stock-split history from yfinance into the events table.

Fetches the full .splits Series for each active ticker, filters out
non-split adjustment factors (spinoff ratios where either side > 50),
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
from datetime import date

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


def _format_ratio(factor: float) -> str:
    """Convert yfinance split factor to 'X:1' or '1:X' string."""
    if factor >= 1:
        int_factor = int(factor)
        if factor == int_factor:
            return f"{int_factor}:1"
        # Non-integer forward split (rare, e.g., 1.5:1 = 3:2)
        from fractions import Fraction
        frac = Fraction(factor).limit_denominator(100)
        return f"{frac.numerator}:{frac.denominator}"
    else:
        # Reverse split: factor < 1, e.g., 0.5 → 1:2
        inv = 1 / factor
        int_inv = int(round(inv))
        return f"1:{int_inv}"


# ── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_all_splits_sync(symbol: str) -> list[dict]:
    """Fetch full split history from yfinance. Returns list of {split_date, split_ratio}."""
    try:
        ticker = yf.Ticker(symbol)
        splits = ticker.splits
    except Exception:
        return []

    if splits is None or splits.empty:
        return []

    results = []
    for ts, factor in splits.items():
        try:
            split_date = ts.date()
        except AttributeError:
            continue

        ratio_str = _format_ratio(factor)
        if not _is_real_split_ratio(ratio_str):
            tqdm.write(f"  ⊘ {symbol}: skipped non-split adjustment factor {ratio_str} on {split_date}")
            continue

        results.append({"split_date": split_date, "split_ratio": ratio_str})

    return results


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

async def _process_ticker(ticker: Ticker, loop) -> tuple[bool, int]:
    """Fetch + upsert all splits with retries. Returns (ok, inserted_count)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            splits = await loop.run_in_executor(
                None, _fetch_all_splits_sync, ticker.symbol
            )
            if not splits:
                return True, 0

            inserted = 0
            async with AsyncSessionLocal() as session:
                for s in splits:
                    if await _upsert_split_event(session, ticker, s["split_date"], s["split_ratio"]):
                        inserted += 1
                await session.commit()
            return True, inserted
        except Exception as exc:
            last_exc = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)

    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed stock-split history from yfinance")
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
    inserted_total = 0
    failed_list: list[str] = []

    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]

    with tqdm(total=len(candidates), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [_process_ticker(t, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, inserted) in zip(batch, results):
                if ok:
                    succeeded += 1
                    inserted_total += inserted
                else:
                    failed_list.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=succeeded, new=inserted_total, fail=len(failed_list))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)

    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {succeeded} tickers processed  📊 {inserted_total} split events inserted  ✗ {len(failed_list)} failed")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 50}")
    return 1 if failed_list else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
