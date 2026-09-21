"""Backtest the v2 engine on historical earnings_features.

Reports momentum-only at -15% AND -10% side by side, per fold,
each fold vs its own baseline, mean/median actual_5d, moved-enough share.

Fail criterion: the chosen cutoff (-15%) must beat its fold baseline
in all 3 folds with positive mean 5d move, or we stop.

Also reports vol gate sensitivity at implied/historical ratios 1.0, 1.2, 1.5.

CLI
---
    python -m app.scripts.backtest_v2
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature
from app.models.ivy_backtest_run import IvyBacktestRun
from app.services.ivy_backtest import summarize
from app.services.ivy_v2 import MIN_PRIOR_N, MOMENTUM_CUTOFF

FOLDS = [
    ("Fold 1 (2023)", date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
    ("Fold 2 (2024)", date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
    ("Fold 3 (2025-26)", date(2024, 12, 31), date(2025, 1, 1), date(2026, 12, 31)),
]


def fold_label(name: str) -> str:
    """ "Fold 3 (2025-26)" -> "2025-26": the years a reader is told the rule was tested on."""
    return name[name.index("(") + 1:name.index(")")]

CUTOFFS_TO_TEST = [-0.15, -0.10]


@dataclass
class PickRecord:
    actual_5d: float
    prior_avg_abs_5d: float | None
    hit: bool
    moved_enough: bool


def _evaluate(
    events: list[dict],
    momentum_cutoff: float,
    min_prior_n: int,
) -> list[PickRecord]:
    """Apply v2 gates (history + momentum) and return qualifying picks."""
    picks = []
    for ev in events:
        if ev["actual_5d"] is None:
            continue
        if ev["prior_n"] is None or ev["prior_n"] < min_prior_n:
            continue
        if ev["momentum_20d"] is None or ev["momentum_20d"] > momentum_cutoff * 100:
            continue

        actual = ev["actual_5d"]
        expected = ev["prior_avg_abs_5d"]
        hit = actual > 0
        moved_enough = expected is not None and actual >= 0.5 * expected
        picks.append(PickRecord(
            actual_5d=actual,
            prior_avg_abs_5d=expected,
            hit=hit,
            moved_enough=moved_enough,
        ))
    return picks


def _stats_line(picks: list[PickRecord]) -> dict:
    """Compute summary stats for a set of picks."""
    n = len(picks)
    if n == 0:
        return {"n": 0, "hits": 0, "hit_rate": 0, "mean_5d": 0, "median_5d": 0, "moved_pct": 0}
    hits = sum(p.hit for p in picks)
    actuals = [p.actual_5d for p in picks]
    mean_5d = sum(actuals) / n
    sorted_a = sorted(actuals)
    median_5d = sorted_a[n // 2] if n % 2 == 1 else (sorted_a[n // 2 - 1] + sorted_a[n // 2]) / 2
    moved = sum(p.moved_enough for p in picks)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": hits / n,
        "mean_5d": mean_5d,
        "median_5d": median_5d,
        "moved_pct": moved / n,
    }


def _baseline(events: list[dict]) -> dict:
    """Compute baseline stats for all events with actual_5d."""
    with_5d = [e for e in events if e["actual_5d"] is not None]
    n = len(with_5d)
    if n == 0:
        return {"n": 0, "up_rate": 0, "mean_5d": 0}
    ups = sum(1 for e in with_5d if e["actual_5d"] > 0)
    mean_5d = sum(e["actual_5d"] for e in with_5d) / n
    return {"n": n, "up_rate": ups / n, "mean_5d": mean_5d}


async def main() -> None:
    async with ScriptSessionLocal() as session:
        result = await session.execute(
            select(EarningsFeature).order_by(EarningsFeature.event_date)
        )
        all_rows = result.scalars().all()

    print(f"Loaded {len(all_rows)} earnings features\n")

    events = []
    for r in all_rows:
        events.append({
            "event_date": r.event_date,
            "symbol": r.symbol,
            "momentum_20d": float(r.momentum_20d) if r.momentum_20d is not None else None,
            "prior_n": int(r.prior_n) if r.prior_n is not None else None,
            "prior_avg_abs_5d": float(r.prior_avg_abs_5d) if r.prior_avg_abs_5d is not None else None,
            "prior_up_5d_rate": float(r.prior_up_5d_rate) if r.prior_up_5d_rate is not None else None,
            "actual_5d": float(r.actual_5d) if r.actual_5d is not None else None,
            "decision": r.decision,  # v1 decision for comparison
        })

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1: Dual cutoff comparison per fold
    # ═══════════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("DUAL CUTOFF COMPARISON: -15% vs -10% momentum, per fold vs fold baseline")
    print("=" * 110)

    header = (f"  {'Fold':<18} {'Cutoff':>7} {'N':>5} {'Hits':>5} "
              f"{'HitRate':>8} {'Baseline':>9} {'Lift':>7} "
              f"{'Mean5d':>8} {'Med5d':>8} {'Moved%':>7}")
    print(header)
    print("  " + "─" * (len(header) - 2))

    chosen_passes_all = True
    chosen_folds: list[dict] = []   # stored in ivy_backtest_runs for /ivy

    for fold_name, train_end, test_start, test_end in FOLDS:
        test_events = [e for e in events if test_start <= e["event_date"] <= test_end]
        bl = _baseline(test_events)

        for cutoff in CUTOFFS_TO_TEST:
            picks = _evaluate(test_events, cutoff, MIN_PRIOR_N)
            s = _stats_line(picks)
            lift = s["hit_rate"] - bl["up_rate"]
            marker = " ← chosen" if cutoff == MOMENTUM_CUTOFF else ""

            print(f"  {fold_name:<18} {cutoff*100:>6.0f}% {s['n']:>5} {s['hits']:>5} "
                  f"{s['hit_rate']*100:>7.1f}% {bl['up_rate']*100:>8.1f}% {lift*100:>+6.1f}pp "
                  f"{s['mean_5d']:>+7.2f}% {s['median_5d']:>+7.2f}% {s['moved_pct']*100:>6.1f}%{marker}")

            # Check fail criterion for chosen cutoff
            if cutoff == MOMENTUM_CUTOFF:
                chosen_folds.append({
                    "label": fold_label(fold_name), "setups": s["n"], "hits": s["hits"],
                    "base_n": bl["n"], "base_ups": round(bl["up_rate"] * bl["n"]),
                })
                if s["hit_rate"] <= bl["up_rate"] or s["mean_5d"] <= 0:
                    chosen_passes_all = False

        print()

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2: v1 comparison
    # ═══════════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("V1 COMPARISON: v1 decision='bullish' hit rate at 5d, per fold")
    print("=" * 110)

    for fold_name, train_end, test_start, test_end in FOLDS:
        test_events = [e for e in events if test_start <= e["event_date"] <= test_end]
        bl = _baseline(test_events)

        # v1 bullish picks
        v1_picks = [e for e in test_events
                    if e["decision"] == "bullish" and e["actual_5d"] is not None]
        v1_n = len(v1_picks)
        v1_hits = sum(1 for e in v1_picks if e["actual_5d"] > 0)
        v1_rate = v1_hits / v1_n if v1_n > 0 else 0
        v1_mean = sum(e["actual_5d"] for e in v1_picks) / v1_n if v1_n > 0 else 0

        # v2 chosen picks
        v2_picks = _evaluate(test_events, MOMENTUM_CUTOFF, MIN_PRIOR_N)
        v2_s = _stats_line(v2_picks)

        print(f"  {fold_name:<18}  v1: {v1_n:>4} picks, {v1_rate*100:.1f}% hit, mean {v1_mean:+.2f}%  |  "
              f"v2: {v2_s['n']:>4} picks, {v2_s['hit_rate']*100:.1f}% hit, mean {v2_s['mean_5d']:+.2f}%  |  "
              f"baseline: {bl['up_rate']*100:.1f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3: Vol gate sensitivity analysis
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 110}")
    print("VOL GATE SENSITIVITY: how many -15% qualifiers survive at various implied/historical ratios")
    print("(Since IV history is sparse, this simulates what would happen if implied_move were Nx historical)")
    print("=" * 110)

    # All qualifying events (across entire dataset)
    all_qualifying = []
    for ev in events:
        if ev["actual_5d"] is None:
            continue
        if ev["prior_n"] is None or ev["prior_n"] < MIN_PRIOR_N:
            continue
        if ev["momentum_20d"] is None or ev["momentum_20d"] > MOMENTUM_CUTOFF * 100:
            continue
        if ev["prior_avg_abs_5d"] is None or ev["prior_avg_abs_5d"] <= 0:
            continue
        all_qualifying.append(ev)

    test_ratios = [1.0, 1.2, 1.5, 2.0]
    print(f"\n  Total qualifying events with prior_avg_abs_5d > 0: {len(all_qualifying)}")
    print(f"\n  {'Implied/Historical':>20} {'Survive':>8} {'Refused':>8} {'Survive%':>9} "
          f"{'SurvivorHitRate':>16} {'RefusedHitRate':>16}")
    print("  " + "─" * 85)

    for ratio in test_ratios:
        # Simulate: implied_move = ratio × prior_avg_abs_5d
        # Vol gate passes if ratio ≤ IV_PREMIUM_CAP (1.2)
        survivors = []
        refused = []
        for ev in all_qualifying:
            simulated_implied = ratio * ev["prior_avg_abs_5d"]
            if simulated_implied > 1.20 * ev["prior_avg_abs_5d"]:
                refused.append(ev)
            else:
                survivors.append(ev)

        s_n = len(survivors)
        r_n = len(refused)
        s_hits = sum(1 for e in survivors if e["actual_5d"] > 0)
        r_hits = sum(1 for e in refused if e["actual_5d"] > 0)
        s_rate = s_hits / s_n * 100 if s_n > 0 else 0
        r_rate = r_hits / r_n * 100 if r_n > 0 else 0

        print(f"  {ratio:>18.1f}x {s_n:>8} {r_n:>8} {s_n/(s_n+r_n)*100:>8.1f}% "
              f"{s_rate:>15.1f}% {r_rate:>15.1f}%")

    # Per-fold breakdown for the cap ratio
    print(f"\n  Per-fold at IV_PREMIUM_CAP = {1.20}x (events where simulated implied > 1.2x historical are refused):")
    for fold_name, train_end, test_start, test_end in FOLDS:
        fold_qual = [e for e in all_qualifying if test_start <= e["event_date"] <= test_end]
        refused = [e for e in fold_qual if True]  # at 1.2x, nothing is refused (1.2 <= 1.2)
        # Actually: ratio=1.2 means implied = 1.2 * hist, gate is implied > 1.2 * hist → 1.2*h > 1.2*h is false → all pass
        # At ratio=1.5: implied = 1.5 * hist, 1.5*h > 1.2*h → refused
        # Show ratio=1.3 as requested
        for sim_ratio in [1.0, 1.2, 1.3, 1.5]:
            survivors = [e for e in fold_qual
                         if sim_ratio * e["prior_avg_abs_5d"] <= 1.20 * e["prior_avg_abs_5d"]]
            refused = [e for e in fold_qual
                       if sim_ratio * e["prior_avg_abs_5d"] > 1.20 * e["prior_avg_abs_5d"]]
            s_n = len(survivors)
            total = len(fold_qual)
            print(f"    {fold_name:<18} ratio={sim_ratio:.1f}x  survive: {s_n}/{total} ({s_n/total*100:.0f}%)" if total > 0 else f"    {fold_name:<18} ratio={sim_ratio:.1f}x  no qualifying events")

    # ═══════════════════════════════════════════════════════════════════════════
    # STORE THE RESULT (every run, pass or fail) so pages render real numbers
    # ═══════════════════════════════════════════════════════════════════════════
    summary = summarize(chosen_folds)
    as_of = max((e["event_date"] for e in events if e["actual_5d"] is not None), default=date.today())
    async with ScriptSessionLocal() as session:
        session.add(IvyBacktestRun(
            as_of_date=as_of,
            momentum_cutoff_pct=round(MOMENTUM_CUTOFF * 100, 2),
            min_prior_quarters=MIN_PRIOR_N,
            folds=summary["folds"],
            setups=summary["setups"], hits=summary["hits"], hit_rate=summary["hit_rate"],
            base_n=summary["base_n"], base_rate=summary["base_rate"],
            passed=chosen_passes_all,
        ))
        await session.commit()
    print(f"\nStored backtest run: {summary['setups']} setups, hit rate {summary['hit_rate'] * 100:.1f}% "
          f"vs base rate {summary['base_rate'] * 100:.1f}% over {summary['base_n']} earnings events, as of {as_of}")

    # ═══════════════════════════════════════════════════════════════════════════
    # FAIL CRITERION CHECK
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 110}")
    if chosen_passes_all:
        print(f"PASS: Chosen cutoff ({MOMENTUM_CUTOFF*100:.0f}%) beats fold baseline in all 3 folds "
              f"with positive mean 5d move.")
    else:
        print(f"FAIL: Chosen cutoff ({MOMENTUM_CUTOFF*100:.0f}%) does NOT beat fold baseline in all "
              f"3 folds or has non-positive mean 5d move. STOP and revisit thresholds.")
        sys.exit(1)
    print("=" * 110)


if __name__ == "__main__":
    asyncio.run(main())
