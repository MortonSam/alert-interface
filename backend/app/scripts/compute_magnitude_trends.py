"""Compute per-ticker magnitude trend stats and store in magnitude_trend_snapshots.

For each active ticker with sufficient earnings history (>=8 quarters with 1d move),
computes the average absolute 1d move for the last 4 and prior 4 quarters, then
derives the trend label using the threshold from thresholds.py.

CLI
---
    python -m app.scripts.compute_magnitude_trends
    python -m app.scripts.compute_magnitude_trends --symbol AAPL
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.thresholds import MAGNITUDE_DECREASE_THRESHOLD, MAGNITUDE_INCREASE_THRESHOLD

COMPUTATION_VERSION = 1
MIN_QUARTERS = 8
WINDOW = 4


def _compute_trend(recent_avg: float, prior_avg: float) -> str:
    """Derive trend label from recent vs prior averages."""
    if prior_avg < 0.01:
        return "stable"
    pct_change = (recent_avg - prior_avg) / prior_avg
    if pct_change > MAGNITUDE_INCREASE_THRESHOLD:
        return "increasing"
    if pct_change < MAGNITUDE_DECREASE_THRESHOLD:
        return "decreasing"
    return "stable"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute per-ticker magnitude trend stats"
    )
    parser.add_argument("--symbol", default=None, help="Single symbol (for testing)")
    args = parser.parse_args()

    today = date.today()

    async with AsyncSessionLocal() as session:
        # 1. Fetch active tickers
        q = select(Ticker).where(Ticker.is_active.is_(True))
        if args.symbol:
            q = q.where(Ticker.symbol == args.symbol.upper())
        tickers = list((await session.execute(q.order_by(Ticker.symbol))).scalars().all())

        if not tickers:
            print("No tickers found.")
            return 0

        upserted = 0
        skipped = 0
        from app.services.price_history_exclusion import exclusion_list
        excluded = await exclusion_list(session, "Magnitude trend snapshot")

        for ticker in tickers:
            if ticker.symbol in excluded:
                skipped += 1
                continue
            # 2. Get earnings reactions ordered by date asc with non-null 1d move
            rows = (await session.execute(
                select(HistoricalReaction.pct_change_1d)
                .where(
                    HistoricalReaction.ticker_id == ticker.id,
                    HistoricalReaction.event_type == EventType.EARNINGS,
                    HistoricalReaction.pct_change_1d.isnot(None),
                )
                .order_by(HistoricalReaction.event_date.asc())
            )).all()

            total = len(rows)
            if total < MIN_QUARTERS:
                skipped += 1
                continue

            abs_1d_all = [abs(float(r.pct_change_1d)) for r in rows]

            recent_4 = abs_1d_all[-WINDOW:]
            prior_4 = abs_1d_all[-(WINDOW * 2):-WINDOW]

            recent_avg = round(sum(recent_4) / WINDOW, 4) if len(recent_4) == WINDOW else None
            prior_avg = round(sum(prior_4) / WINDOW, 4) if len(prior_4) == WINDOW else None

            trend: str | None = None
            if recent_avg is not None and prior_avg is not None:
                trend = _compute_trend(recent_avg, prior_avg)

            # 3. Upsert
            stmt = sa.text("""
                INSERT INTO magnitude_trend_snapshots
                    (id, symbol, recent_avg_abs_1d, prior_avg_abs_1d,
                     recent_window, prior_window, trend, as_of_date,
                     computation_version, created_at)
                VALUES
                    (gen_random_uuid(), :symbol, :recent_avg, :prior_avg,
                     :window, :window, :trend, :as_of_date,
                     :version, :now)
                ON CONFLICT (symbol, as_of_date) DO UPDATE SET
                    recent_avg_abs_1d = :recent_avg,
                    prior_avg_abs_1d = :prior_avg,
                    recent_window = :window,
                    prior_window = :window,
                    trend = :trend,
                    computation_version = :version,
                    created_at = :now
            """)
            await session.execute(stmt, {
                "symbol": ticker.symbol,
                "recent_avg": recent_avg,
                "prior_avg": prior_avg,
                "window": WINDOW,
                "trend": trend,
                "as_of_date": today,
                "version": COMPUTATION_VERSION,
                "now": datetime.now(timezone.utc),
            })
            upserted += 1

        await session.commit()

    print(f"Upserted {upserted} magnitude trend rows ({skipped} skipped, <{MIN_QUARTERS} quarters).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
