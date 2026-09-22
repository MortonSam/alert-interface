"""Repair earnings rows whose stored outcome contradicts their stored EPS values.

Two causes, handled in order:

1. Split basis. The old upsert froze the estimate once a quarter had an actual;
   a later split restated the actual on the new share count while the estimate
   stayed on the old one (MNST 0.30 vs 0.15 after its 2023 2:1). The estimate
   is re-based by the split factor it differs from the actual by, matching the
   estimate Yahoo now shows for that date, and the outcome is derived from the
   re-based pair.
2. Outcome only. The old upsert also froze `outcome` while a revised actual
   could still be written, so the label stopped matching the numbers. The
   outcome is recomputed from the stored values.

Reports every change with symbol and date. Idempotent.

Usage (inside the backend container or via railway run):
    python -m app.scripts.repair_outcomes            # report only
    python -m app.scripts.repair_outcomes --write    # apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal

from sqlalchemy import text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.scripts.seed_historical_reactions import _compute_outcome, rebased_estimate
from app.services.split_basis import factors_after, load_splits, wrong_basis_factor

ROWS_WITH_SPLIT_AFTER_SQL = """
    SELECT DISTINCT hr.id, hr.ticker_id, t.symbol, hr.event_date, hr.outcome::text AS outcome,
           hr.eps_actual, hr.eps_estimate
    FROM historical_reactions hr
    JOIN tickers t ON t.id = hr.ticker_id
    JOIN events e ON e.ticker_id = hr.ticker_id AND e.event_type = 'split' AND e.event_date > hr.event_date
    WHERE hr.event_type = 'earnings' AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
    ORDER BY t.symbol, hr.event_date
"""

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

UPDATE_SQL = text("""
    UPDATE historical_reactions
    SET eps_estimate = COALESCE(:est, eps_estimate), outcome = CAST(:o AS earnings_outcome_enum)
    WHERE id = :id
""")


async def repair(write: bool) -> int:
    changes: list[tuple] = []   # (id, symbol, date, new_estimate | None, new_outcome)
    async with AsyncSessionLocal() as session:
        # 1. Estimates on a different split basis from their actual
        rebased_ids: set = set()
        print("Split basis:")
        for r in (await session.execute(text(ROWS_WITH_SPLIT_AFTER_SQL))).all():
            factors = factors_after(await load_splits(session, r.ticker_id), r.event_date)
            factor = wrong_basis_factor(r.eps_estimate, r.eps_actual, factors)
            if factor is None:
                continue
            new_est = rebased_estimate(r.eps_estimate, factor)
            new_out = _compute_outcome(new_est, r.eps_actual).value
            rebased_ids.add(r.id)
            changes.append((r.id, r.symbol, r.event_date, new_est, new_out))
            print(f"  {r.symbol:6s} {r.event_date}  actual {float(r.eps_actual):+.2f}  est {float(r.eps_estimate):+.2f}"
                  f" -> {float(new_est):+.2f} (/{factor:g})  {r.outcome} -> {new_out}")
        # 2. Outcomes contradicting the (remaining) stored values
        print("Outcome only:")
        for r in (await session.execute(text(MISMATCH_SQL))).all():
            if r.id in rebased_ids:
                continue
            changes.append((r.id, r.symbol, r.event_date, None, r.expected))
            print(f"  {r.symbol:6s} {r.event_date}  actual {float(r.eps_actual):+.2f}  est {float(r.eps_estimate):+.2f}"
                  f"  {r.outcome} -> {r.expected}")

        symbols = sorted({c[1] for c in changes})
        print(f"\n{len(changes)} row(s) to change across {len(symbols)} ticker(s): {', '.join(symbols)}")
        if not changes:
            return 0
        if not write:
            print("Report only; pass --write to apply.")
            return 0
        for row_id, _, _, new_est, new_out in changes:
            await session.execute(UPDATE_SQL, {"id": row_id, "est": new_est, "o": new_out})
        await session.commit()
        print(f"Updated {len(changes)} row(s). Stored beat statistics for these tickers come from "
              f"earnings_features: run build_features (--skip-yfinance is enough) to recompute them.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="Apply the changes (default: report only)")
    args = parser.parse_args()
    return asyncio.run(repair(args.write))


if __name__ == "__main__":
    sys.exit(main())
