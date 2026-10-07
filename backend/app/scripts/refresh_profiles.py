"""Refresh ticker market caps and names from Finnhub /stock/profile2.

Picks the 120 active tickers with the oldest market_cap_updated_at (nulls first)
and updates market_cap and name.  A Finnhub failure leaves the existing value
untouched (integrity rule).

Usage
-----
    python -m app.scripts.refresh_profiles
"""
from __future__ import annotations
from app.services.redact import redact
from app.services.write_failures import WriteFailures

WRITES = WriteFailures("Refresh profiles (Finnhub)")

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.services.finnhub_client import FinnhubClient

BATCH_LIMIT = 120
COMMIT_EVERY = 20


async def main() -> int:
    updated = 0
    skipped = 0
    failed = 0

    async with ScriptSessionLocal() as session:
        tickers = (await session.execute(
            select(Ticker)
            .where(Ticker.is_active.is_(True))
            .order_by(Ticker.market_cap_updated_at.asc().nulls_first())
            .limit(BATCH_LIMIT)
        )).scalars().all()

        if not tickers:
            print("No active tickers to refresh.")
            return 0

        print(f"Refreshing profiles for {len(tickers)} tickers...")

        finnhub = FinnhubClient()
        try:
            for i, ticker in enumerate(tickers):
                try:
                    profile = await finnhub.get_profile2(ticker.symbol)

                    mcap_m = profile.get("marketCapitalization")
                    if mcap_m and float(mcap_m) > 0:
                        ticker.market_cap = int(float(mcap_m) * 1_000_000)
                    # else: keep existing market_cap (integrity rule)

                    shares_m = profile.get("shareOutstanding")
                    if shares_m and float(shares_m) > 0:
                        ticker.shares_outstanding = int(float(shares_m) * 1_000_000)
                        ticker.shares_as_of = datetime.now(timezone.utc)

                    name = profile.get("name")
                    if ticker.name is None and name:
                        ticker.name = name

                    ticker.market_cap_updated_at = datetime.now(timezone.utc)
                    updated += 1

                except Exception as exc:
                    WRITES.note(ticker.symbol, exc)
                    failed += 1
                    print(f"  ✗ {ticker.symbol}: {redact(exc)}")
                    continue

                # Commit in batches
                if (i + 1) % COMMIT_EVERY == 0:
                    await session.commit()

            await session.commit()
        finally:
            await finnhub.close()

    print(f"\n{'─' * 50}")
    print(f"  ✓ {updated} updated  ⊘ {skipped} skipped  ✗ {failed} failed")
    print(f"{'─' * 50}")
    from app.services.finnhub_client import finnhub_stats
    from app.services.step_outcomes import record_step_fields
    await record_step_fields("Refresh profiles (Finnhub)", {"updated": updated, "skipped": skipped, "failed": failed, "finnhub": finnhub_stats(), "error": None})
    return await WRITES.finish(1 if failed > 10 else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
