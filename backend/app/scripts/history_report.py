"""Earnings depth report — how many tickers have enough history.

Per-ticker: count of events, count with ≥ 3/5/8 prior events,
median |actual_5d|.  Summary: how many tickers pass min_n gates
at various thresholds.

CLI
---
    python -m app.scripts.history_report
"""

from __future__ import annotations

import asyncio
import statistics
from collections import defaultdict

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature


async def main() -> None:
    async with ScriptSessionLocal() as session:
        result = await session.execute(
            select(
                EarningsFeature.symbol,
                EarningsFeature.event_date,
                EarningsFeature.prior_n,
                EarningsFeature.actual_5d,
            ).order_by(EarningsFeature.symbol, EarningsFeature.event_date)
        )
        rows = result.all()

    print(f"Loaded {len(rows)} earnings feature rows\n")

    # Group by symbol
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_symbol[r.symbol].append({
            "event_date": r.event_date,
            "prior_n": int(r.prior_n) if r.prior_n is not None else 0,
            "actual_5d": float(r.actual_5d) if r.actual_5d is not None else None,
        })

    # Per-ticker report
    thresholds = [3, 4, 5, 6, 8]
    ticker_stats = []

    for sym in sorted(by_symbol.keys()):
        events = by_symbol[sym]
        n_events = len(events)
        abs_5ds = [abs(e["actual_5d"]) for e in events if e["actual_5d"] is not None]
        median_abs_5d = statistics.median(abs_5ds) if abs_5ds else None

        counts_above = {}
        for t in thresholds:
            counts_above[t] = sum(1 for e in events if e["prior_n"] >= t)

        ticker_stats.append({
            "symbol": sym,
            "n_events": n_events,
            "median_abs_5d": median_abs_5d,
            "counts_above": counts_above,
        })

    # Print per-ticker table
    header = f"{'Symbol':<8} {'Events':>6} {'Med|5d|':>8}"
    for t in thresholds:
        header += f" {'≥'+str(t)+' prior':>9}"
    print(header)
    print("─" * len(header))

    for ts in ticker_stats:
        line = f"{ts['symbol']:<8} {ts['n_events']:>6}"
        if ts["median_abs_5d"] is not None:
            line += f" {ts['median_abs_5d']:>7.2f}%"
        else:
            line += f" {'n/a':>8}"
        for t in thresholds:
            line += f" {ts['counts_above'][t]:>9}"
        print(line)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY: Tickers passing min_prior_n gates")
    print(f"{'=' * 70}")
    print(f"\n{'Threshold':<12} {'Tickers w/ ≥1 event':>22} {'Tickers w/ ≥5 events':>22}")
    print("─" * 56)
    for t in thresholds:
        tickers_any = sum(1 for ts in ticker_stats if ts["counts_above"][t] >= 1)
        tickers_5 = sum(1 for ts in ticker_stats if ts["counts_above"][t] >= 5)
        print(f"prior_n ≥ {t:<3} {tickers_any:>22} {tickers_5:>22}")

    # Total events passing each threshold
    print(f"\n{'Threshold':<12} {'Total events passing':>22}")
    print("─" * 34)
    for t in thresholds:
        total = sum(ts["counts_above"][t] for ts in ticker_stats)
        print(f"prior_n ≥ {t:<3} {total:>22}")

    # Distribution of prior_n across all events
    all_prior_ns = []
    for sym_events in by_symbol.values():
        for e in sym_events:
            all_prior_ns.append(e["prior_n"])

    print(f"\n{'=' * 70}")
    print("DISTRIBUTION of prior_n across all events")
    print(f"{'=' * 70}")
    if all_prior_ns:
        buckets = [(0, 0), (1, 2), (3, 4), (5, 7), (8, 12), (13, 999)]
        for lo, hi in buckets:
            count = sum(1 for n in all_prior_ns if lo <= n <= hi)
            label = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
            pct = count / len(all_prior_ns) * 100
            print(f"  prior_n {label:>5}: {count:>5} events ({pct:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
