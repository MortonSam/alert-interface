"""Remove duplicate earnings reactions (one report stored under two dates).

For each pair of earnings rows for one ticker within WINDOW_DAYS:
  - eps_estimate and eps_actual identical on both rows -> one report.
      keep the row with pct values; if neither has pct values, keep the row
      with known timing (bmo/amc); delete the other.
  - EPS differs, or the rule does not pick a single row -> print, change nothing.

Dry run by default.

Usage:
    python -m app.scripts.dedupe_earnings_reactions            # dry run
    python -m app.scripts.dedupe_earnings_reactions --write    # apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal as AsyncSessionLocal

WINDOW_DAYS = 45
KNOWN_TIMINGS = {"bmo", "amc"}


def _has_pct(r) -> bool:
    return r["pct_1d"] is not None or r["pct_3d"] is not None or r["pct_5d"] is not None


def _timing(r) -> str:
    t = r["timing"]
    return (getattr(t, "value", t) or "unknown").lower()


def _fmt(r) -> str:
    return (f"{r['event_date']} ({_timing(r)}, {'pct' if _has_pct(r) else 'null'}, "
            f"eps={r['eps_estimate']}/{r['eps_actual']})")


def decide(a: dict, b: dict) -> tuple[dict | None, dict | None, str]:
    """Return (keep, delete, reason). keep/delete are None when nothing changes."""
    if a["eps_estimate"] is None or a["eps_actual"] is None:
        return None, None, "NO CHANGE: EPS missing on first row, cannot prove one report"
    if (a["eps_estimate"], a["eps_actual"]) != (b["eps_estimate"], b["eps_actual"]):
        return None, None, "NO CHANGE: EPS differs"

    pa, pb = _has_pct(a), _has_pct(b)
    if pa != pb:
        keep, drop = (a, b) if pa else (b, a)
        return keep, drop, "same EPS, keep the row with pct values"
    if pa and pb:
        return None, None, "NO CHANGE: same EPS but both rows have pct values"

    ka, kb = _timing(a) in KNOWN_TIMINGS, _timing(b) in KNOWN_TIMINGS
    if ka != kb:
        keep, drop = (a, b) if ka else (b, a)
        return keep, drop, "same EPS, neither has pct, keep the row with known timing"
    return None, None, (
        "NO CHANGE: same EPS, neither has pct, "
        + ("both timings known" if ka else "neither timing known")
    )


async def _run(write: bool) -> int:
    async with AsyncSessionLocal() as session:
        pairs = (await session.execute(text("""
            SELECT t.symbol, hr1.id AS id1, hr2.id AS id2
            FROM historical_reactions hr1
            JOIN historical_reactions hr2
              ON hr1.ticker_id = hr2.ticker_id
             AND hr1.event_type = 'earnings' AND hr2.event_type = 'earnings'
             AND hr2.event_date > hr1.event_date
             AND hr2.event_date - hr1.event_date <= :win
            JOIN tickers t ON t.id = hr1.ticker_id
            ORDER BY t.symbol, hr1.event_date, hr2.event_date
        """), {"win": WINDOW_DAYS})).all()

        print(f"{len(pairs)} pair(s) of earnings rows within {WINDOW_DAYS} days (write={write})\n")

        deleted_ids: set = set()
        n_delete = n_nochange = 0
        for p in pairs:
            if p.id1 in deleted_ids or p.id2 in deleted_ids:
                print(f"{p.symbol}  pair skipped, one row already deleted by an earlier decision")
                continue
            rows = {
                r.id: dict(r._mapping) for r in (await session.execute(text("""
                    SELECT id, event_date, report_timing AS timing,
                           eps_estimate, eps_actual,
                           pct_change_1d AS pct_1d, pct_change_3d AS pct_3d, pct_change_5d AS pct_5d
                    FROM historical_reactions WHERE id IN (:a, :b)
                """), {"a": p.id1, "b": p.id2})).all()
            }
            a, b = rows[p.id1], rows[p.id2]
            keep, drop, reason = decide(a, b)
            print(f"{p.symbol}  {_fmt(a)} <-> {_fmt(b)}")
            if keep is None:
                print(f"    {reason}")
                n_nochange += 1
                continue
            print(f"    KEEP {keep['event_date']}  DELETE {drop['event_date']}  ({reason})")
            n_delete += 1
            deleted_ids.add(drop["id"])
            if write:
                await session.execute(
                    text("DELETE FROM historical_reactions WHERE id = :id"), {"id": drop["id"]}
                )

        if write:
            await session.commit()

    verb = "deleted" if write else "would delete"
    print(f"\nSummary: {n_delete} row(s) {verb}, {n_nochange} pair(s) left unchanged")
    if not write and n_delete:
        print("Dry run. Re-run with --write to apply.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Dedupe earnings reactions stored under two dates")
    ap.add_argument("--write", action="store_true", help="apply deletions (default: dry run)")
    return asyncio.run(_run(ap.parse_args().write))


if __name__ == "__main__":
    sys.exit(main())
