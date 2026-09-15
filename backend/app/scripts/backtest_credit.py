"""Backtest the credit side (short strangle / iron condor proxy).

For every earnings_features event with prior_n >= 8, simulate a
short position where the short strikes sit at spot +/- K * prior_avg_abs_5d.
Proxy payoff (no IV history): the position wins if |actual_5d| <= K * expected,
loses otherwise.

Reports win rate per fold and per K, the naive base rate, and the loss tail
(mean |actual_5d| / expected for losers).

Usage:
    python -m app.scripts.backtest_credit
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature

# Same three held-out folds as backtest_v2 / threshold_search
FOLDS = [
    ("Fold 1 (2023)", date(2023, 1, 1), date(2023, 12, 31)),
    ("Fold 2 (2024)", date(2024, 1, 1), date(2024, 12, 31)),
    ("Fold 3 (2025-26)", date(2025, 1, 1), date(2026, 12, 31)),
]

K_VALUES = [1.0, 1.25, 1.5]

MIN_PRIOR_N = 8
STABLE_PRIOR_N = 12
MOMENTUM_LO = -10.0
MOMENTUM_HI = 10.0


@dataclass
class Row:
    symbol: str
    event_date: date
    prior_n: int
    prior_avg_abs_5d: float
    actual_5d: float
    momentum_20d: float | None


def _load_rows(features: list) -> list[Row]:
    """Filter features to those usable for the backtest."""
    rows = []
    for f in features:
        if f.prior_n is None or f.prior_n < MIN_PRIOR_N:
            continue
        if f.prior_avg_abs_5d is None or float(f.prior_avg_abs_5d) <= 0:
            continue
        if f.actual_5d is None:
            continue
        rows.append(Row(
            symbol=f.symbol,
            event_date=f.event_date,
            prior_n=int(f.prior_n),
            prior_avg_abs_5d=float(f.prior_avg_abs_5d),
            actual_5d=float(f.actual_5d),
            momentum_20d=float(f.momentum_20d) if f.momentum_20d is not None else None,
        ))
    return rows


def _evaluate(rows: list[Row], k: float) -> tuple[int, int, float]:
    """Return (wins, total, mean_overshoot_ratio_for_losers)."""
    wins = 0
    loser_ratios: list[float] = []
    for r in rows:
        expected = r.prior_avg_abs_5d
        threshold = k * expected
        if abs(r.actual_5d) <= threshold:
            wins += 1
        else:
            loser_ratios.append(abs(r.actual_5d) / expected)
    mean_overshoot = sum(loser_ratios) / len(loser_ratios) if loser_ratios else 0.0
    return wins, len(rows), mean_overshoot


def _naive_rate(rows: list[Row], k: float) -> float:
    """Naive base rate: fraction where |actual_5d| <= k * overall_mean_abs_5d."""
    if not rows:
        return 0.0
    overall_mean = sum(abs(r.actual_5d) for r in rows) / len(rows)
    threshold = k * overall_mean
    wins = sum(1 for r in rows if abs(r.actual_5d) <= threshold)
    return wins / len(rows) if rows else 0.0


def _print_table(title: str, rows_by_fold: dict[str, list[Row]]) -> None:
    """Print win rate table for all folds and K values."""
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")

    # Header
    print(f"  {'':28s}", end="")
    for k in K_VALUES:
        print(f"  K={k:<5.2f}          ", end="")
    print()
    print(f"  {'':28s}", end="")
    for _ in K_VALUES:
        print(f"  {'win%':>5s} {'n':>5s} {'tail':>5s}", end="")
    print()
    print(f"  {'-' * 68}")

    # Per fold
    for fold_name, rows in rows_by_fold.items():
        if not rows:
            print(f"  {fold_name:28s}  (no data)")
            continue
        print(f"  {fold_name:28s}", end="")
        for k in K_VALUES:
            wins, total, tail = _evaluate(rows, k)
            wr = wins / total * 100 if total else 0
            print(f"  {wr:5.1f} {total:5d} {tail:5.2f}", end="")
        print()

    # All folds combined
    all_rows = [r for rows in rows_by_fold.values() for r in rows]
    if all_rows:
        print(f"  {'-' * 68}")
        print(f"  {'ALL':28s}", end="")
        for k in K_VALUES:
            wins, total, tail = _evaluate(all_rows, k)
            wr = wins / total * 100 if total else 0
            print(f"  {wr:5.1f} {total:5d} {tail:5.2f}", end="")
        print()

        # Naive baseline
        print(f"  {'Naive baseline':28s}", end="")
        for k in K_VALUES:
            nr = _naive_rate(all_rows, k) * 100
            print(f"  {nr:5.1f} {'':5s} {'':5s}", end="")
        print()


async def _run() -> int:
    async with ScriptSessionLocal() as session:
        result = await session.execute(
            select(EarningsFeature).order_by(EarningsFeature.event_date)
        )
        all_features = result.scalars().all()

    rows = _load_rows(all_features)
    if not rows:
        print("[credit-backtest] No usable rows.")
        return 1

    print(f"[credit-backtest] {len(rows)} events with prior_n >= {MIN_PRIOR_N}")

    # Split into folds
    def fold_filter(rows: list[Row], start: date, end: date) -> list[Row]:
        return [r for r in rows if start <= r.event_date <= end]

    # ── Report 1: All qualifying events (prior_n >= 8) ──────────────────
    folds_all: dict[str, list[Row]] = {}
    for name, start, end in FOLDS:
        folds_all[name] = fold_filter(rows, start, end)
    _print_table(f"All events (prior_n >= {MIN_PRIOR_N})", folds_all)

    # ── Report 2: Stable subset (prior_n >= 12) ─────────────────────────
    stable = [r for r in rows if r.prior_n >= STABLE_PRIOR_N]
    folds_stable: dict[str, list[Row]] = {}
    for name, start, end in FOLDS:
        folds_stable[name] = fold_filter(stable, start, end)
    _print_table(f"Stable subset (prior_n >= {STABLE_PRIOR_N})", folds_stable)

    # ── Report 3: Neutral momentum (-10% to +10%) ───────────────────────
    neutral = [r for r in rows if r.momentum_20d is not None
               and MOMENTUM_LO <= r.momentum_20d <= MOMENTUM_HI]
    if neutral:
        folds_neutral: dict[str, list[Row]] = {}
        for name, start, end in FOLDS:
            folds_neutral[name] = fold_filter(neutral, start, end)
        _print_table(f"Neutral momentum ({MOMENTUM_LO:.0f}% to {MOMENTUM_HI:.0f}%)", folds_neutral)
    else:
        print(f"\n  [skipped] Neutral momentum: no rows have momentum_20d populated")

    # ── Report 4: Stable + neutral combined ──────────────────────────────
    both = [r for r in rows if r.prior_n >= STABLE_PRIOR_N
            and r.momentum_20d is not None
            and MOMENTUM_LO <= r.momentum_20d <= MOMENTUM_HI]
    if both:
        folds_both: dict[str, list[Row]] = {}
        for name, start, end in FOLDS:
            folds_both[name] = fold_filter(both, start, end)
        _print_table("Stable + neutral combined", folds_both)
    else:
        print(f"  [skipped] Stable + neutral: no rows have momentum_20d populated")

    # ── Loss tail detail ─────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  Loss tail detail (losers only: |actual_5d| > K * expected)")
    print(f"{'=' * 72}")
    print(f"  {'Subset':28s}", end="")
    for k in K_VALUES:
        print(f"  K={k:<5.2f}     ", end="")
    print()
    print(f"  {'':28s}", end="")
    for _ in K_VALUES:
        print(f"  {'n':>4s} {'avg':>5s}", end="")
    print()
    print(f"  {'-' * 68}")

    tail_subsets = [
        (f"All (prior_n >= {MIN_PRIOR_N})", rows),
        (f"Stable (prior_n >= {STABLE_PRIOR_N})", stable),
    ]
    if neutral:
        tail_subsets.append(("Neutral momentum", neutral))
    if both:
        tail_subsets.append(("Stable + neutral", both))

    for label, subset in tail_subsets:
        print(f"  {label:28s}", end="")
        for k in K_VALUES:
            losers = [r for r in subset if abs(r.actual_5d) > k * r.prior_avg_abs_5d]
            if losers:
                avg_ratio = sum(abs(r.actual_5d) / r.prior_avg_abs_5d for r in losers) / len(losers)
                print(f"  {len(losers):4d} {avg_ratio:5.2f}", end="")
            else:
                print(f"  {'0':>4s} {'--':>5s}", end="")
        print()

    print()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
