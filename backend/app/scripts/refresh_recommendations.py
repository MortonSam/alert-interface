"""Refresh analyst recommendation trends from Finnhub.

Picks the 120 active tickers with the oldest fetched_at (nulls first)
and upserts monthly consensus data from /stock/recommendation.

Usage
-----
    python -m app.scripts.refresh_recommendations
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select, func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.ticker import Ticker
from app.services.finnhub_client import FinnhubClient

BATCH_LIMIT = 120
COMMIT_EVERY = 20


async def main() -> int:
    updated = 0
    failed = 0

    async with ScriptSessionLocal() as session:
        # Subquery: latest fetched_at per ticker
        latest_fetch = (
            select(
                AnalystRecommendation.ticker_id,
                sa_func.max(AnalystRecommendation.fetched_at).label("max_fetched"),
            )
            .group_by(AnalystRecommendation.ticker_id)
            .subquery()
        )

        tickers = (await session.execute(
            select(Ticker)
            .outerjoin(latest_fetch, Ticker.id == latest_fetch.c.ticker_id)
            .where(Ticker.is_active.is_(True))
            .order_by(latest_fetch.c.max_fetched.asc().nulls_first())
            .limit(BATCH_LIMIT)
        )).scalars().all()

        if not tickers:
            print("No active tickers to refresh.")
            return 0

        print(f"Refreshing recommendations for {len(tickers)} tickers...")

        finnhub = FinnhubClient()
        try:
            for i, ticker in enumerate(tickers):
                try:
                    trends = await finnhub.get_recommendation_trends(ticker.symbol)
                    if not trends:
                        continue

                    now = datetime.now(timezone.utc)
                    for row in trends:
                        period = date.fromisoformat(row["period"])
                        stmt = pg_insert(AnalystRecommendation).values(
                            ticker_id=ticker.id,
                            period=period,
                            strong_buy=row.get("strongBuy", 0),
                            buy=row.get("buy", 0),
                            hold=row.get("hold", 0),
                            sell=row.get("sell", 0),
                            strong_sell=row.get("strongSell", 0),
                            fetched_at=now,
                        ).on_conflict_do_update(
                            constraint="uq_analyst_rec_ticker_period",
                            set_={
                                "strong_buy": row.get("strongBuy", 0),
                                "buy": row.get("buy", 0),
                                "hold": row.get("hold", 0),
                                "sell": row.get("sell", 0),
                                "strong_sell": row.get("strongSell", 0),
                                "fetched_at": now,
                            },
                        )
                        await session.execute(stmt)

                    updated += 1

                except Exception as exc:
                    failed += 1
                    print(f"  ✗ {ticker.symbol}: {exc}")
                    continue

                if (i + 1) % COMMIT_EVERY == 0:
                    await session.commit()

            await session.commit()
        finally:
            await finnhub.close()

    print(f"\n{'─' * 50}")
    print(f"  ✓ {updated} updated  ✗ {failed} failed")
    print(f"{'─' * 50}")
    return 1 if failed > 10 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
