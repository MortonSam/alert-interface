"""One-shot repair: recompute outcome classifications using strict inequality.

Fixes rows where the old $0.01-tolerance rule misclassified beat/miss as meet.
Safe to re-run — idempotent.

Usage (inside the backend container or via railway run):
    python -m app.scripts.fix_outcome_classifications
    python -m app.scripts.fix_outcome_classifications --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.database import AsyncSessionLocal


async def fix(dry_run: bool) -> int:
    async with AsyncSessionLocal() as session:
        # Find all meet rows where actual != estimate (these were misclassified)
        rows = await session.execute(text("""
            SELECT hr.id, t.symbol, hr.event_date, hr.eps_estimate, hr.eps_actual
            FROM historical_reactions hr
            JOIN tickers t ON t.id = hr.ticker_id
            WHERE hr.outcome = 'meet'
              AND hr.eps_estimate IS NOT NULL
              AND hr.eps_actual IS NOT NULL
              AND hr.eps_actual != hr.eps_estimate
            ORDER BY t.symbol, hr.event_date
        """))
        changes = []
        for row in rows:
            rid, sym, dt, est, act = row
            new = "beat" if act > est else "miss"
            changes.append((rid, sym, dt, est, act, new))

        print(f"Rows to reclassify: {len(changes)}")
        for rid, sym, dt, est, act, new in changes:
            print(f"  {sym:<8} {dt}  est={est}  actual={act}  meet→{new}")

        if dry_run:
            print("\n--dry-run: no changes written.")
            return 0

        # Apply updates
        beat_ids = [str(r[0]) for r in changes if r[5] == "beat"]
        miss_ids = [str(r[0]) for r in changes if r[5] == "miss"]

        if beat_ids:
            await session.execute(
                text("UPDATE historical_reactions SET outcome = 'beat' WHERE id = ANY(:ids)"),
                {"ids": beat_ids},
            )
        if miss_ids:
            await session.execute(
                text("UPDATE historical_reactions SET outcome = 'miss' WHERE id = ANY(:ids)"),
                {"ids": miss_ids},
            )

        await session.commit()
        beats = len(beat_ids)
        misses = len(miss_ids)
        print(f"\nApplied: {beats} meet→beat, {misses} meet→miss ({beats + misses} total)")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix outcome classifications (strict inequality)")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without applying")
    args = parser.parse_args()
    return asyncio.run(fix(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
