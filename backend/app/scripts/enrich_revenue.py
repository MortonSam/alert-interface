"""Backfill revenue (and missing EPS) on historical_reactions via Finnhub.

Finnhub's /stock/earnings endpoint returns per-quarter records with:
  actual, estimate, period, quarter, year,
  revenueActual, revenueEstimate, surprise, surprisePercent, symbol.

This script matches each Finnhub quarter to existing EARNINGS reaction rows
by finding the Finnhub record whose `period` (fiscal quarter end) is the
latest date strictly before the reaction's event_date and within 120 days.

Only fills data — no price recomputation.

CLI
---
    python -m app.scripts.enrich_revenue              # all tickers
    python -m app.scripts.enrich_revenue AAPL NVDA     # specific tickers
    python -m app.scripts.enrich_revenue --limit 5     # testing
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.seed_historical_reactions import _compute_outcome
from app.services.finnhub_client import FinnhubClient

# ── Rate-limit tuning ────────────────────────────────────────────────────────

BATCH_SIZE = 5
BATCH_SLEEP = 5.0          # seconds between batches → ~50 calls/min
RETRY_DELAYS = (5, 10, 20)  # longer cooldown for Finnhub 429s

# ── Matching ──────────────────────────────────────────────────────────────────

MAX_PERIOD_GAP_DAYS = 120  # max days between fiscal quarter end and event_date


def _match_quarter(
    event_date: date,
    quarters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the Finnhub quarter whose period is the latest date strictly
    before event_date and within MAX_PERIOD_GAP_DAYS."""
    best: dict[str, Any] | None = None
    best_period: date | None = None
    for q in quarters:
        period_str = q.get("period")
        if not period_str:
            continue
        try:
            period = date.fromisoformat(period_str)
        except (ValueError, TypeError):
            continue
        if period >= event_date:
            continue
        if (event_date - period).days > MAX_PERIOD_GAP_DAYS:
            continue
        if best_period is None or period > best_period:
            best = q
            best_period = period
    return best


# ── Per-ticker enrichment ─────────────────────────────────────────────────────

async def _enrich_ticker(
    finnhub: FinnhubClient,
    ticker: Ticker,
) -> tuple[int, int, int]:
    """Enrich one ticker. Returns (rows_updated, rows_unmatched, eps_backfilled)."""
    quarters = await finnhub.get_earnings_surprises(ticker.symbol)
    if not quarters:
        return 0, 0, 0

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(HistoricalReaction)
                .where(
                    HistoricalReaction.ticker_id == ticker.id,
                    HistoricalReaction.event_type == EventType.EARNINGS,
                )
                .order_by(HistoricalReaction.event_date)
            )
        ).scalars().all()

        if not rows:
            return 0, 0, 0

        updated = 0
        unmatched = 0
        eps_backfilled = 0

        for row in rows:
            match = _match_quarter(row.event_date, quarters)
            if match is None:
                unmatched += 1
                continue

            # Always write revenue
            rev_est = match.get("revenueEstimate")
            rev_act = match.get("revenueActual")
            row.revenue_estimate = int(rev_est) if rev_est is not None else None
            row.revenue_actual = int(rev_act) if rev_act is not None else None

            # Backfill EPS only if DB value is NULL
            eps_changed = False
            if row.eps_estimate is None and match.get("estimate") is not None:
                row.eps_estimate = Decimal(str(round(float(match["estimate"]), 4)))
                eps_changed = True
            if row.eps_actual is None and match.get("actual") is not None:
                row.eps_actual = Decimal(str(round(float(match["actual"]), 4)))
                eps_changed = True

            if eps_changed:
                row.outcome = _compute_outcome(row.eps_estimate, row.eps_actual)
                eps_backfilled += 1

            updated += 1

        await session.commit()

    return updated, unmatched, eps_backfilled


# ── Retry wrapper ─────────────────────────────────────────────────────────────

async def _enrich_ticker_with_retry(
    finnhub: FinnhubClient,
    ticker: Ticker,
) -> tuple[bool, int, int, int, int]:
    """Returns (ok, rows_updated, rows_unmatched, eps_backfilled, retries_used)."""
    retries_used = 0
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            upd, unm, eps = await _enrich_ticker(finnhub, ticker)
            return True, upd, unm, eps, retries_used
        except Exception as exc:
            last_exc = exc
            retries_used += 1
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)
    print(f"  ✗ {ticker.symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0, 0, 0, retries_used


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill revenue via Finnhub")
    parser.add_argument("tickers", nargs="*", metavar="TICKER",
                        help="Specific ticker(s) to enrich")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap the ticker list at N (for testing)")
    args = parser.parse_args()

    # Load tickers
    async with AsyncSessionLocal() as session:
        if args.tickers:
            symbols = [s.upper() for s in args.tickers]
            tickers: list[Ticker] = list(
                (await session.execute(
                    select(Ticker).where(Ticker.symbol.in_(symbols)).order_by(Ticker.symbol)
                )).scalars().all()
            )
            found = {t.symbol for t in tickers}
            for s in symbols:
                if s not in found:
                    print(f"  ⚠  {s} not in DB — skipping")
        else:
            tickers = list(
                (await session.execute(
                    select(Ticker).order_by(Ticker.symbol)
                )).scalars().all()
            )

    if args.limit is not None:
        tickers = tickers[: args.limit]

    if not tickers:
        print("No tickers to process.")
        return 0

    print(f"Enriching {len(tickers)} tickers with Finnhub revenue data...\n")

    finnhub = FinnhubClient()
    total_updated = 0
    total_unmatched = 0
    total_eps = 0
    total_retries = 0
    failed_count = 0

    batches = [tickers[i : i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    try:
        for batch_idx, batch in enumerate(batches):
            tasks = [_enrich_ticker_with_retry(finnhub, t) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, upd, unm, eps, retries) in zip(batch, results):
                if ok:
                    total_updated += upd
                    total_unmatched += unm
                    total_eps += eps
                    total_retries += retries
                    if upd:
                        print(f"  {ticker.symbol}: {upd} rows updated"
                              f"{f', {eps} EPS backfilled' if eps else ''}")
                else:
                    failed_count += 1
                    total_retries += retries

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)
    finally:
        await finnhub.close()

    # Summary
    processed = len(tickers) - failed_count
    print()
    print(f"── ENRICHMENT SUMMARY {'─' * 30}")
    print(f"  {processed:,} tickers processed")
    print(f"  {total_updated:,} rows updated with revenue")
    print(f"  {total_unmatched:,} reaction rows unmatched (no Finnhub quarter)")
    print(f"  {total_eps:,} EPS backfilled from Finnhub")
    print(f"  {total_retries:,} rate-limit retries")
    if failed_count:
        print(f"  {failed_count:,} tickers failed")
    print(f"{'─' * 52}")

    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
