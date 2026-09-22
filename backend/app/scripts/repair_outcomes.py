"""Repair earnings rows whose stored outcome contradicts their stored EPS values.

The old upsert froze `outcome` once a quarter had an actual, while a revised
actual could still be written, so the label stopped matching the numbers.
This recomputes outcome from the stored eps_estimate / eps_actual for every
mismatched row and reports each change. Idempotent.

Usage (inside the backend container or via railway run):
    python -m app.scripts.repair_outcomes            # report only
    python -m app.scripts.repair_outcomes --write    # apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal as AsyncSessionLocal

MISMATCH_SQL = """
    SELECT hr.id, t.symbol, hr.event_date, hr.outcome::text AS outcome, hr.eps_actual, hr.eps_estimate,
           CASE WHEN hr.eps_actual > hr.eps_estimate THEN 'beat'
                WHEN hr.eps_actual < hr.eps_estimate THEN 'miss'
                ELSE 'meet' END AS expected
    FROM historical_reactions hr
    JOIN tickers t ON t.id = hr.ticker_id
    WHERE hr.event_type = 'earnings'
      AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
      AND hr.outcome::text <> CASE WHEN hr.eps_actual > hr.eps_estimate THEN 'beat'
                                   WHEN hr.eps_actual < hr.eps_estimate THEN 'miss'
                                   ELSE 'meet' END
    ORDER BY t.symbol, hr.event_date
"""


async def repair(write: bool) -> int:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(MISMATCH_SQL))).all()
        symbols = sorted({r.symbol for r in rows})
        for r in rows:
            print(f"  {r.symbol:6s} {r.event_date}  actual {float(r.eps_actual):+.2f}  est {float(r.eps_estimate):+.2f}"
                  f"  {r.outcome} -> {r.expected}")
        print(f"\n{len(rows)} mismatched row(s) across {len(symbols)} ticker(s): {', '.join(symbols)}")
        if not rows:
            return 0
        if not write:
            print("Report only; pass --write to apply.")
            return 0
        for r in rows:
            await session.execute(
                text("UPDATE historical_reactions SET outcome = CAST(:o AS earnings_outcome_enum) WHERE id = :id"),
                {"o": r.expected, "id": r.id},
            )
        await session.commit()
        print(f"Updated {len(rows)} row(s). Stored beat statistics for these tickers come from "
              f"earnings_features: run build_features (--skip-yfinance is enough) to recompute them.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="Apply the changes (default: report only)")
    args = parser.parse_args()
    return asyncio.run(repair(args.write))


if __name__ == "__main__":
    sys.exit(main())
