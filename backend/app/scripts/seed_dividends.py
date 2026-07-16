"""Seed ex-dividend dates from yfinance into the events table.

For each ticker, fetches exDividendDate from yfinance's Ticker.info and
upserts into events with event_type=EX_DIVIDEND.

CLI
---
    python -m app.scripts.seed_dividends
    python -m app.scripts.seed_dividends --limit 5
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


# ── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_dividend_info_sync(symbol: str) -> dict | None:
    """Fetch ex-dividend date and dividend rate from yfinance.
    Returns dict with keys: ex_date, dividend_rate, or None if unavailable."""
    try:
        info = yf.Ticker(symbol).info
    except Exception:
        return None

    ex_ts = info.get("exDividendDate")
    if ex_ts is None:
        return None

    # exDividendDate is a Unix timestamp
    try:
        ex_date = datetime.utcfromtimestamp(ex_ts).date()
    except (TypeError, ValueError, OSError):
        return None

    # Only keep if within 30 days past or any future date
    if ex_date < date.today() - timedelta(days=30):
        return None

    dividend_rate = info.get("dividendRate")
    return {
        "ex_date": ex_date,
        "dividend_rate": float(dividend_rate) if dividend_rate else None,
    }


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_dividend_event(
    session,
    ticker: Ticker,
    ex_date: date,
    dividend_rate: float | None,
) -> bool:
    """Insert ex-dividend event if not already present. Returns True if inserted."""
    existing = await session.scalar(
        select(Event.id).where(
            Event.ticker_id == ticker.id,
            Event.event_date == ex_date,
            Event.event_type == EventType.EX_DIVIDEND,
        )
    )
    if existing is not None:
        return False

    metadata = {}
    if dividend_rate is not None:
        metadata["dividend_amount"] = dividend_rate

    event = Event(
        ticker_id=ticker.id,
        event_type=EventType.EX_DIVIDEND,
        event_date=ex_date,
        title=f"{ticker.symbol} Ex-Dividend",
        source=DataSource.YFINANCE,
        is_confirmed=True,
        metadata_=metadata,
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
                None, _fetch_dividend_info_sync, ticker.symbol
            )
            if info is None:
                return True, False  # ok but no dividend data

            async with AsyncSessionLocal() as session:
                inserted = await _upsert_dividend_event(
                    session, ticker, info["ex_date"], info["dividend_rate"]
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
    parser = argparse.ArgumentParser(description="Seed ex-dividend dates from yfinance")
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
    print(f"  ✓ {succeeded} tickers processed  📊 {inserted_count} ex-div events inserted  ✗ {len(failed_list)} failed")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 50}")
    return 1 if failed_list else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
