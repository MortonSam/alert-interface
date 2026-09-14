"""Walk-forward grid search for v2 threshold tuning.

Searches over momentum_cutoff, min_prior_n, base_rate_floor,
min_cohort_n, and require_earnings_lean_positive.  Uses cohort-level
pooled base rates (not per-ticker) and 3 held-out year folds.

CLI
---
    python -m app.scripts.threshold_search
"""

from __future__ import annotations

import asyncio
import itertools
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature

# ── Grid dimensions ──────────────────────────────────────────────────────────

MOMENTUM_CUTOFFS = [-0.20, -0.15, -0.125, -0.10, -0.075, -0.05]
MIN_PRIOR_NS = [4, 6, 8, 10, 12]
BASE_RATE_FLOORS = [0.54, 0.55, 0.56, 0.57, 0.58, 0.60, 0.62]
MIN_COHORT_NS = [50, 100, 150]
REQUIRE_EARNINGS_LEAN_POSITIVE = [True, False]

# ── Folds ────────────────────────────────────────────────────────────────────

FOLDS = [
    ("Fold 1", date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
    ("Fold 2", date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
    ("Fold 3", date(2024, 12, 31), date(2025, 1, 1), date(2026, 12, 31)),
]

MIN_PICKS_PER_YEAR = 40


@dataclass
class FoldResult:
    name: str
    n_picks: int
    n_hits: int
    hit_rate: float
    test_years: float  # number of years in test period


@dataclass
class ComboResult:
    momentum_cutoff: float
    min_prior_n: int
    base_rate_floor: float
    min_cohort_n: int
    require_earnings_lean_positive: bool
    fold_results: list[FoldResult]
    avg_hit_rate: float
    avg_picks_per_year: float
    meets_floor: bool


def _bucket_key(momentum_20d: float | None, momentum_cutoff: float) -> str:
    """Assign event to a momentum bucket."""
    if momentum_20d is None:
        return "mom_unknown"
    if momentum_20d <= momentum_cutoff * 100:  # momentum_20d is in pct
        return "mom_deep_neg"
    elif momentum_20d <= 0:
        return "mom_mild_neg"
    elif momentum_20d <= abs(momentum_cutoff * 100):
        return "mom_mild_pos"
    else:
        return "mom_strong_pos"


def _earnings_lean_sign(prior_up_5d_rate: float | None) -> str:
    """Classify earnings lean as positive/negative/neutral."""
    if prior_up_5d_rate is None:
        return "neutral"
    if prior_up_5d_rate > 0.5:
        return "positive"
    elif prior_up_5d_rate < 0.5:
        return "negative"
    return "neutral"


def _compute_cohort_rates(
    events: list[dict],
    momentum_cutoff: float,
) -> dict[str, dict]:
    """Compute cohort base rates pooled across tickers by setup bucket.

    Returns {bucket_key: {"n": int, "up_rate": float}}
    """
    buckets: dict[str, list[bool]] = defaultdict(list)
    for ev in events:
        if ev["actual_5d"] is None:
            continue
        mom_key = _bucket_key(ev["momentum_20d"], momentum_cutoff)
        lean_sign = _earnings_lean_sign(ev["prior_up_5d_rate"])
        key = f"{mom_key}|{lean_sign}"
        buckets[key].append(ev["actual_5d"] > 0)

    result = {}
    for key, outcomes in buckets.items():
        n = len(outcomes)
        up_rate = sum(outcomes) / n if n > 0 else 0.0
        result[key] = {"n": n, "up_rate": up_rate}
    return result


def _evaluate_fold(
    train_events: list[dict],
    test_events: list[dict],
    momentum_cutoff: float,
    min_prior_n: int,
    base_rate_floor: float,
    min_cohort_n: int,
    require_earnings_lean_positive: bool,
    test_years: float,
) -> FoldResult:
    """Evaluate a single fold with given parameters."""

    # Build cohort base rates from TRAIN data only
    cohort_rates = _compute_cohort_rates(train_events, momentum_cutoff)

    picks = []
    for ev in test_events:
        if ev["actual_5d"] is None:
            continue

        # History gate
        prior_n = ev["prior_n"]
        if prior_n is None or prior_n < min_prior_n:
            continue

        # Setup bucket for this event
        mom_key = _bucket_key(ev["momentum_20d"], momentum_cutoff)
        lean_sign = _earnings_lean_sign(ev["prior_up_5d_rate"])
        bucket_key = f"{mom_key}|{lean_sign}"

        # Path A: momentum reversal
        momentum_20d = ev["momentum_20d"]
        path_a = momentum_20d is not None and momentum_20d <= momentum_cutoff * 100

        # Path B: cohort base rate meets floor
        cohort = cohort_rates.get(bucket_key, {"n": 0, "up_rate": 0.0})
        path_b = cohort["n"] >= min_cohort_n and cohort["up_rate"] >= base_rate_floor

        # Earnings lean positive requirement
        if require_earnings_lean_positive:
            if ev["prior_up_5d_rate"] is None or ev["prior_up_5d_rate"] <= 0.5:
                path_a = False  # Must also have positive earnings lean

        if not (path_a or path_b):
            continue

        picks.append(ev["actual_5d"] > 0)

    n_picks = len(picks)
    n_hits = sum(picks)
    hit_rate = n_hits / n_picks if n_picks > 0 else 0.0

    return FoldResult(
        name="",
        n_picks=n_picks,
        n_hits=n_hits,
        hit_rate=hit_rate,
        test_years=test_years,
    )


async def main() -> None:
    async with ScriptSessionLocal() as session:
        # Load all earnings features
        result = await session.execute(
            select(
                EarningsFeature.ticker_id,
                EarningsFeature.event_date,
                EarningsFeature.symbol,
                EarningsFeature.momentum_20d,
                EarningsFeature.prior_n,
                EarningsFeature.prior_up_5d_rate,
                EarningsFeature.prior_avg_abs_5d,
                EarningsFeature.actual_5d,
            ).order_by(EarningsFeature.event_date)
        )
        rows = result.all()

    print(f"Loaded {len(rows)} earnings features")

    events = []
    for r in rows:
        events.append({
            "ticker_id": r.ticker_id,
            "event_date": r.event_date,
            "symbol": r.symbol,
            "momentum_20d": float(r.momentum_20d) if r.momentum_20d is not None else None,
            "prior_n": int(r.prior_n) if r.prior_n is not None else None,
            "prior_up_5d_rate": float(r.prior_up_5d_rate) if r.prior_up_5d_rate is not None else None,
            "prior_avg_abs_5d": float(r.prior_avg_abs_5d) if r.prior_avg_abs_5d is not None else None,
            "actual_5d": float(r.actual_5d) if r.actual_5d is not None else None,
        })

    # Count events with actual_5d
    with_5d = sum(1 for e in events if e["actual_5d"] is not None)
    print(f"Events with actual_5d: {with_5d}")

    # Generate all parameter combos
    combos = list(itertools.product(
        MOMENTUM_CUTOFFS,
        MIN_PRIOR_NS,
        BASE_RATE_FLOORS,
        MIN_COHORT_NS,
        REQUIRE_EARNINGS_LEAN_POSITIVE,
    ))
    print(f"Testing {len(combos)} parameter combinations across {len(FOLDS)} folds\n")

    results: list[ComboResult] = []

    for mc, mpn, brf, mcn, relp in combos:
        fold_results = []
        for fold_name, train_end, test_start, test_end in FOLDS:
            train = [e for e in events if e["event_date"] <= train_end]
            test = [e for e in events if test_start <= e["event_date"] <= test_end]

            test_years = (test_end - test_start).days / 365.25
            if test_years < 0.5:
                test_years = 1.0  # minimum

            fr = _evaluate_fold(train, test, mc, mpn, brf, mcn, relp, test_years)
            fr.name = fold_name
            fold_results.append(fr)

        total_picks = sum(fr.n_picks for fr in fold_results)
        total_hits = sum(fr.n_hits for fr in fold_results)
        total_test_years = sum(fr.test_years for fr in fold_results)

        avg_hit_rate = total_hits / total_picks if total_picks > 0 else 0.0
        avg_picks_per_year = total_picks / total_test_years if total_test_years > 0 else 0.0

        # Check ≥40 picks per year in each fold
        meets_floor = all(
            fr.n_picks / fr.test_years >= MIN_PICKS_PER_YEAR
            for fr in fold_results
        )

        results.append(ComboResult(
            momentum_cutoff=mc,
            min_prior_n=mpn,
            base_rate_floor=brf,
            min_cohort_n=mcn,
            require_earnings_lean_positive=relp,
            fold_results=fold_results,
            avg_hit_rate=avg_hit_rate,
            avg_picks_per_year=avg_picks_per_year,
            meets_floor=meets_floor,
        ))

    # Filter to those meeting the 40-pick floor, sort by avg hit rate
    qualifying = [r for r in results if r.meets_floor]
    qualifying.sort(key=lambda r: r.avg_hit_rate, reverse=True)

    print("=" * 100)
    print(f"RESULTS: {len(qualifying)} of {len(results)} combos meet the ≥{MIN_PICKS_PER_YEAR} picks/year floor")
    print("=" * 100)

    if not qualifying:
        print("\nNo combos met the pick-rate floor. Showing top 5 by hit rate (ignoring floor):")
        results.sort(key=lambda r: r.avg_hit_rate, reverse=True)
        qualifying = results[:5]

    top = qualifying[:5]
    for rank, combo in enumerate(top, 1):
        print(f"\n{'─' * 100}")
        print(f"  Rank {rank}:  momentum ≤ {combo.momentum_cutoff*100:.1f}%  |  "
              f"min_prior_n ≥ {combo.min_prior_n}  |  "
              f"base_rate ≥ {combo.base_rate_floor*100:.0f}%  |  "
              f"min_cohort_n ≥ {combo.min_cohort_n}  |  "
              f"require_earnings_lean_pos = {combo.require_earnings_lean_positive}")
        print(f"  Avg hit rate: {combo.avg_hit_rate*100:.1f}%  |  "
              f"Avg picks/year: {combo.avg_picks_per_year:.0f}  |  "
              f"Meets floor: {combo.meets_floor}")
        print(f"  {'Fold':<8} {'Picks':>6} {'Hits':>6} {'Hit Rate':>10} {'Picks/Yr':>10}")
        for fr in combo.fold_results:
            picks_yr = fr.n_picks / fr.test_years
            print(f"  {fr.name:<8} {fr.n_picks:>6} {fr.n_hits:>6} "
                  f"{fr.hit_rate*100:>9.1f}% {picks_yr:>9.0f}")

    # Pooled baseline
    baseline_5d = [e for e in events if e["actual_5d"] is not None]
    baseline_up = sum(1 for e in baseline_5d if e["actual_5d"] > 0)
    print(f"\n{'=' * 100}")
    print(f"BASELINE (pooled): {baseline_up}/{len(baseline_5d)} events up at 5d = "
          f"{baseline_up/len(baseline_5d)*100:.1f}%")

    # Per-fold baselines
    print(f"\nPer-fold baselines (all events with actual_5d in test window):")
    print(f"  {'Fold':<8} {'Events':>7} {'Up':>6} {'Up Rate':>9}")
    for fold_name, _train_end, test_start, test_end in FOLDS:
        fold_evts = [e for e in events
                     if e["actual_5d"] is not None
                     and test_start <= e["event_date"] <= test_end]
        fold_up = sum(1 for e in fold_evts if e["actual_5d"] > 0)
        rate = fold_up / len(fold_evts) * 100 if fold_evts else 0
        print(f"  {fold_name:<8} {len(fold_evts):>7} {fold_up:>6} {rate:>8.1f}%")

    # Show top 5 with per-fold lift over baseline
    print(f"\nTop 5 with per-fold lift over fold baseline:")
    fold_baselines = {}
    for fold_name, _train_end, test_start, test_end in FOLDS:
        fold_evts = [e for e in events
                     if e["actual_5d"] is not None
                     and test_start <= e["event_date"] <= test_end]
        fold_up = sum(1 for e in fold_evts if e["actual_5d"] > 0)
        fold_baselines[fold_name] = fold_up / len(fold_evts) if fold_evts else 0

    for rank, combo in enumerate(top, 1):
        print(f"\n  Rank {rank}: momentum ≤ {combo.momentum_cutoff*100:.1f}%  "
              f"min_n ≥ {combo.min_prior_n}  base ≥ {combo.base_rate_floor*100:.0f}%  "
              f"cohort ≥ {combo.min_cohort_n}  earn_lean_pos={combo.require_earnings_lean_positive}")
        print(f"  {'Fold':<8} {'Hit Rate':>9} {'Baseline':>9} {'Lift':>7}")
        for fr in combo.fold_results:
            bl = fold_baselines.get(fr.name, 0)
            lift = fr.hit_rate - bl
            print(f"  {fr.name:<8} {fr.hit_rate*100:>8.1f}% {bl*100:>8.1f}% {lift*100:>+6.1f}pp")

    print(f"{'=' * 100}")

    # ── Path decomposition for Rank 1 winner ─────────────────────────────────
    if top:
        winner = top[0]
        print(f"\n{'=' * 100}")
        print(f"PATH DECOMPOSITION for Rank 1 winner")
        print(f"  momentum ≤ {winner.momentum_cutoff*100:.1f}%  |  "
              f"min_prior_n ≥ {winner.min_prior_n}  |  "
              f"base_rate ≥ {winner.base_rate_floor*100:.0f}%  |  "
              f"min_cohort_n ≥ {winner.min_cohort_n}  |  "
              f"require_earnings_lean_pos = {winner.require_earnings_lean_positive}")
        print(f"{'=' * 100}")

        for fold_name, train_end, test_start, test_end in FOLDS:
            train = [e for e in events if e["event_date"] <= train_end]
            test = [e for e in events
                    if e["actual_5d"] is not None
                    and test_start <= e["event_date"] <= test_end]

            cohort_rates = _compute_cohort_rates(train, winner.momentum_cutoff)

            mom_only = []    # path A only
            cohort_only = [] # path B only
            both = []        # both paths
            all_picks = []   # union

            for ev in test:
                prior_n = ev["prior_n"]
                if prior_n is None or prior_n < winner.min_prior_n:
                    continue

                mom_key = _bucket_key(ev["momentum_20d"], winner.momentum_cutoff)
                lean_sign = _earnings_lean_sign(ev["prior_up_5d_rate"])
                bucket_key = f"{mom_key}|{lean_sign}"

                momentum_20d = ev["momentum_20d"]
                path_a = momentum_20d is not None and momentum_20d <= winner.momentum_cutoff * 100

                if winner.require_earnings_lean_positive:
                    if ev["prior_up_5d_rate"] is None or ev["prior_up_5d_rate"] <= 0.5:
                        path_a = False

                cohort = cohort_rates.get(bucket_key, {"n": 0, "up_rate": 0.0})
                path_b = (cohort["n"] >= winner.min_cohort_n
                          and cohort["up_rate"] >= winner.base_rate_floor)

                if not (path_a or path_b):
                    continue

                hit = ev["actual_5d"] > 0
                actual = ev["actual_5d"]
                expected = ev["prior_avg_abs_5d"]
                # "moved enough" = actual_5d >= +0.5 × prior_avg_abs_5d
                moved_enough = (expected is not None
                                and actual >= 0.5 * expected)

                record = {"hit": hit, "actual_5d": actual,
                          "moved_enough": moved_enough}
                all_picks.append(record)

                if path_a and path_b:
                    both.append(record)
                elif path_a:
                    mom_only.append(record)
                else:
                    cohort_only.append(record)

            def _stats(records: list[dict], label: str) -> str:
                n = len(records)
                if n == 0:
                    return f"  {label:<16} {'n/a':>6}"
                hits = sum(r["hit"] for r in records)
                actuals = [r["actual_5d"] for r in records]
                mean_5d = sum(actuals) / n
                sorted_a = sorted(actuals)
                median_5d = sorted_a[n // 2] if n % 2 == 1 else (sorted_a[n // 2 - 1] + sorted_a[n // 2]) / 2
                moved = sum(r["moved_enough"] for r in records)
                return (f"  {label:<16} {n:>5}  {hits:>5}  "
                        f"{hits/n*100:>7.1f}%  {mean_5d:>+7.2f}%  "
                        f"{median_5d:>+7.2f}%  {moved:>5}  "
                        f"{moved/n*100:>6.1f}%")

            print(f"\n  {fold_name}:")
            print(f"  {'Path':<16} {'N':>5}  {'Hits':>5}  "
                  f"{'HitRate':>8}  {'Mean5d':>8}  {'Med5d':>8}  "
                  f"{'Moved':>5}  {'Moved%':>7}")
            print(f"  {'─' * 72}")
            print(_stats(mom_only, "Momentum only"))
            print(_stats(cohort_only, "Cohort only"))
            print(_stats(both, "Both"))
            print(_stats(all_picks, "ALL PICKS"))

        print(f"\n  Note: 'Moved' = actual_5d >= +0.5 × prior_avg_abs_5d (enough to cover half the expected move)")


if __name__ == "__main__":
    asyncio.run(main())
