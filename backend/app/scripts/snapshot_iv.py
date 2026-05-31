"""Snapshot today's ATM implied volatility and 20-day realized vol for all active tickers.

Run daily (via ``make refresh`` or standalone) to build iv_history for future IV Rank.
Upserts on (symbol, date) — safe to re-run multiple times per day.

Usage
-----
    python -m app.scripts.snapshot_iv
    python -m app.scripts.snapshot_iv --symbol AAPL   # single ticker

TODO: Once >= 3–6 months of iv_history has accrued, compute true IV Rank/Percentile
the same way as realized vol rank (trailing 252 readings, rank + percentile) and display
both side-by-side on the ticker page.  The spread between IV Rank and RV Rank
(implied vs actual movement cost) is itself a tradeable signal:
  - High IV Rank, Low RV Rank  → options overpriced vs realised movement (sell vol)
  - Low IV Rank,  High RV Rank → options cheap vs realised movement (buy vol)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

import sqlalchemy as sa

from app.database import AsyncSessionLocal
from app.models.ticker import Ticker
from app.services.yfinance_client import YFinanceClient


async def _snapshot_one(symbol: str, today: date) -> dict:
    """Fetch ATM IV + 20d RV for one ticker and upsert into iv_history."""
    loop = asyncio.get_event_loop()

    iv_data, rv_data = await asyncio.gather(
        loop.run_in_executor(None, YFinanceClient.get_atm_iv_snapshot, symbol),
        loop.run_in_executor(None, YFinanceClient.get_realized_vol_data, symbol),
    )

    atm_iv: float | None       = iv_data.get("atm_iv")
    current_price: float | None = iv_data.get("current_price")
    atm_strike: float | None   = iv_data.get("atm_strike")
    realized_vol_20d: float | None = rv_data.get("current_rv")

    stmt = sa.text("""
        INSERT INTO iv_history
            (id, symbol, date, atm_iv, realized_vol_20d, atm_strike, current_price, created_at)
        VALUES
            (gen_random_uuid(), :symbol, :date,
             :atm_iv, :realized_vol_20d, :atm_strike, :current_price, now())
        ON CONFLICT (symbol, date) DO UPDATE SET
            atm_iv           = EXCLUDED.atm_iv,
            realized_vol_20d = EXCLUDED.realized_vol_20d,
            atm_strike       = EXCLUDED.atm_strike,
            current_price    = EXCLUDED.current_price
    """)

    async with AsyncSessionLocal() as session:
        await session.execute(stmt, {
            "symbol": symbol,
            "date": today,
            "atm_iv": atm_iv,
            "realized_vol_20d": realized_vol_20d,
            "atm_strike": atm_strike,
            "current_price": current_price,
        })
        await session.commit()

    return {
        "symbol": symbol,
        "atm_iv": atm_iv,
        "realized_vol_20d": realized_vol_20d,
        "current_price": current_price,
        "atm_strike": atm_strike,
    }


async def main(only_symbol: str | None = None) -> int:
    today = date.today()
    print(f"\nIV Snapshot — {today}")
    print("─" * 60)

    if only_symbol:
        symbols = [only_symbol.upper()]
    else:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                sa.select(Ticker.symbol)
                .where(Ticker.is_active.is_(True))
                .order_by(Ticker.symbol)
            )
            symbols = [row[0] for row in result.fetchall()]

    print(f"Snapshotting {len(symbols)} ticker(s)...\n")
    ok = err = 0

    for symbol in symbols:
        try:
            row = await _snapshot_one(symbol, today)
            iv_str = f"{row['atm_iv'] * 100:.2f}%" if row["atm_iv"] is not None else "—"
            rv_str = f"{row['realized_vol_20d'] * 100:.2f}%" if row["realized_vol_20d"] is not None else "—"
            px_str = f"${row['current_price']:.2f}" if row["current_price"] is not None else "—"
            sk_str = f"${row['atm_strike']:.2f}" if row["atm_strike"] is not None else "—"
            print(f"  {symbol:8s}  price={px_str:10s}  ATM_strike={sk_str:10s}  ATM_IV={iv_str:8s}  RV-20d={rv_str}")
            ok += 1
        except Exception as exc:
            print(f"  {symbol:8s}  ERROR: {exc}")
            err += 1

    print(f"\n  Done: {ok} OK, {err} error(s).")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snapshot ATM IV + realized vol for tickers.")
    parser.add_argument("--symbol", metavar="SYM", default=None,
                        help="Snapshot a single ticker only (default: all active).")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(only_symbol=args.symbol)))
