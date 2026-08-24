"""Mark tickers as inactive and delete their historical reactions.

Usage
-----
    python -m app.scripts.deactivate_tickers EA SATS

Idempotent: running twice on the same symbol is a no-op.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import delete, select, update

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker


async def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]]
    if not symbols:
        print("Usage: python -m app.scripts.deactivate_tickers SYMBOL [SYMBOL ...]")
        return 1

    async with AsyncSessionLocal() as session:
        for sym in symbols:
            ticker = (await session.execute(
                select(Ticker).where(Ticker.symbol == sym)
            )).scalar_one_or_none()

            if ticker is None:
                print(f"  ⚠  {sym}: not found in DB, skipping")
                continue

            if not ticker.is_active:
                # Already inactive — still delete reactions if any remain
                del_result = await session.execute(
                    delete(HistoricalReaction).where(
                        HistoricalReaction.ticker_id == ticker.id
                    )
                )
                if del_result.rowcount:
                    print(f"  🗑 {sym}: already inactive, deleted {del_result.rowcount} leftover reaction(s)")
                else:
                    print(f"  ✓  {sym}: already inactive, no reactions to delete")
                continue

            # Mark inactive
            await session.execute(
                update(Ticker).where(Ticker.id == ticker.id).values(is_active=False)
            )

            # Delete reactions
            del_result = await session.execute(
                delete(HistoricalReaction).where(
                    HistoricalReaction.ticker_id == ticker.id
                )
            )
            print(f"  ✓  {sym}: marked inactive, deleted {del_result.rowcount} reaction(s)")

        await session.commit()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
