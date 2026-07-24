"""Close expired alert picks by fetching their official close price.

Usage:
    python -m app.scripts.close_alert_picks
    make close-picks
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.alert_pick import AlertPick
from app.services.yfinance_client import YFinanceClient


async def _close_picks() -> int:
    today_str = date.today().isoformat()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.expiration < today_str,
            )
        )).scalars().all()

        if not rows:
            print("[close-picks] No expired open picks to close.")
            return 0

        closed = 0
        for pick in rows:
            close_price = YFinanceClient.get_close_on_date(pick.symbol, pick.expiration)
            if close_price is None:
                print(f"[close-picks] {pick.symbol} exp={pick.expiration}: no close found, skipping")
                continue

            pick.status = "closed"
            pick.closed_at = datetime.now(timezone.utc)
            pick.close_price = close_price
            closed += 1
            print(f"[close-picks] {pick.symbol} exp={pick.expiration}: closed at ${close_price}")

        await session.commit()
        print(f"[close-picks] Done. Closed {closed}/{len(rows)} expired picks.")
        return 0


def main() -> int:
    return asyncio.run(_close_picks())


if __name__ == "__main__":
    sys.exit(main())
