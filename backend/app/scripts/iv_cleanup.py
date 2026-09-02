"""One-shot diagnostic + cleanup for iv_history corruption.

Run inside container:
    python -m app.scripts.iv_cleanup --diagnose
    python -m app.scripts.iv_cleanup --clean
    python -m app.scripts.iv_cleanup --production-sql
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.database import engine


async def diagnose():
    """Print NaN rows and AVB/MRNA price series for Aug 2026."""
    async with engine.connect() as conn:
        # 1. NaN current_price rows
        r = await conn.execute(text(
            "SELECT date, COUNT(*) as cnt "
            "FROM iv_history "
            "WHERE current_price <> current_price "
            "GROUP BY date ORDER BY date"
        ))
        rows = r.fetchall()
        print("=== NaN current_price rows by date ===")
        total = 0
        for row in rows:
            print(f"  {row[0]}  count={row[1]}")
            total += row[1]
        print(f"  TOTAL: {total} rows\n")

        # 2. Full series for split-suspect symbols
        for sym in ("AVB", "MRNA"):
            r = await conn.execute(text(
                "SELECT date, current_price, atm_iv "
                "FROM iv_history "
                "WHERE symbol = :sym "
                "ORDER BY date"
            ), {"sym": sym})
            rows = r.fetchall()
            print(f"=== {sym} full iv_history ===")
            for row in rows:
                print(f"  {row[0]}  price={row[1]}  atm_iv={row[2]}")
            print()


async def clean():
    """Delete NaN and split-corrupt rows from local DB."""
    async with engine.begin() as conn:
        # 1. Delete NaN current_price rows (any symbol, any date)
        r = await conn.execute(text(
            "DELETE FROM iv_history WHERE current_price <> current_price"
        ))
        print(f"Deleted {r.rowcount} NaN current_price rows")

        # 2. AVB: neighbors are $182-195. Aug 25 at $68.14 is bogus
        #    split-adjusted (real price / 2.793). Delete rows < $100.
        r = await conn.execute(text(
            "DELETE FROM iv_history "
            "WHERE symbol = 'AVB' AND current_price < 100"
        ))
        print(f"Deleted {r.rowcount} AVB split-corrupt rows (price < $100)")

        # 3. MRNA: neighbors are $46-80. Aug 25 at $138.89 is reverse
        #    split-adjusted (real price * ~2.33). Delete rows > $100.
        r = await conn.execute(text(
            "DELETE FROM iv_history "
            "WHERE symbol = 'MRNA' AND current_price > 100"
        ))
        print(f"Deleted {r.rowcount} MRNA split-corrupt rows (price > $100)")


def print_production_sql():
    """Print DELETE statements for Sam to run in Railway Postgres Console."""
    print("-- iv_history corruption cleanup")
    print("-- Run these in the Railway Postgres Console (production).")
    print("-- Verify row counts before committing.\n")

    print("-- 1. NaN current_price rows (2026-08-19 batch + any others)")
    print("--    NaN <> NaN is true in Postgres, so this catches all NaN values.")
    print("BEGIN;")
    print("SELECT COUNT(*) FROM iv_history WHERE current_price <> current_price;")
    print("DELETE FROM iv_history WHERE current_price <> current_price;")
    print("-- Expect: ~40-60 rows (the 2026-08-19 batch)")
    print("COMMIT;\n")

    print("-- 2. AVB bogus split-adjustment (real price ~$182-195, corrupt ~$65-68)")
    print("BEGIN;")
    print("SELECT date, current_price FROM iv_history")
    print("  WHERE symbol = 'AVB' AND current_price < 100 ORDER BY date;")
    print("DELETE FROM iv_history")
    print("  WHERE symbol = 'AVB' AND current_price < 100;")
    print("COMMIT;\n")

    print("-- 3. MRNA reverse split-adjustment (real price ~$46-80, corrupt ~$138-174)")
    print("BEGIN;")
    print("SELECT date, current_price FROM iv_history")
    print("  WHERE symbol = 'MRNA' AND current_price > 100 ORDER BY date;")
    print("DELETE FROM iv_history")
    print("  WHERE symbol = 'MRNA' AND current_price > 100;")
    print("COMMIT;")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--production-sql", action="store_true")
    args = parser.parse_args()

    if args.diagnose:
        asyncio.run(diagnose())
    elif args.clean:
        asyncio.run(clean())
    elif args.production_sql:
        print_production_sql()


if __name__ == "__main__":
    main()
