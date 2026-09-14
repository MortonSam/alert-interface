"""Backtest the shadow logistic-regression model on the same three folds as v2.

For each fold: train on train-years, predict test-year.
Reports AUC, hit rate at multiple probability thresholds vs fold baseline
and vs v2's rule, plus overlap analysis.

CLI
---
    python -m app.scripts.backtest_shadow
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

import numpy as np
from sklearn.metrics import roc_auc_score
from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature
from app.services.ivy_shadow import FEATURE_COLS, train, predict
from app.services.ivy_v2 import MIN_PRIOR_N, MOMENTUM_CUTOFF

FOLDS = [
    ("Fold 1 (2023)", date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
    ("Fold 2 (2024)", date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
    ("Fold 3 (2025-26)", date(2024, 12, 31), date(2025, 1, 1), date(2026, 12, 31)),
]

THRESHOLDS = [0.55, 0.58, 0.60, 0.62, 0.65]


def _is_v2_pick(row) -> bool:
    """Would v2 pick this row? (momentum + history gates only, no vol gate)."""
    if row.prior_n is None or int(row.prior_n) < MIN_PRIOR_N:
        return False
    if row.momentum_20d is None or float(row.momentum_20d) > MOMENTUM_CUTOFF * 100:
        return False
    return True


def _baseline_up_rate(rows) -> float:
    with_5d = [r for r in rows if r.actual_5d is not None]
    if not with_5d:
        return 0.0
    return sum(1 for r in with_5d if float(r.actual_5d) > 0) / len(with_5d)


async def main() -> None:
    async with ScriptSessionLocal() as session:
        result = await session.execute(
            select(EarningsFeature).order_by(EarningsFeature.event_date)
        )
        all_rows = result.scalars().all()

    print(f"Loaded {len(all_rows)} earnings features\n")

    for fold_name, train_end, test_start, test_end in FOLDS:
        train_rows = [r for r in all_rows if r.event_date <= train_end]
        test_rows = [r for r in all_rows
                     if test_start <= r.event_date <= test_end
                     and r.actual_5d is not None]

        if len(train_rows) < 50:
            print(f"\n{fold_name}: insufficient training data ({len(train_rows)} rows), skipping")
            continue

        print(f"\n{'=' * 100}")
        print(f"  {fold_name}   train: <={train_end}  test: {test_start} to {test_end}")
        print(f"  train rows: {len(train_rows)}   test rows: {len(test_rows)}")
        print(f"{'=' * 100}")

        # Train
        tr = train(all_rows, cutoff_date=test_start)
        model = tr.model

        print(f"\n  Training: {tr.n_train} rows, {tr.n_positive} positive ({tr.n_positive/tr.n_train*100:.1f}%)")
        print(f"  Top features (standardized coef):")
        for col, coef in tr.feature_importance[:5]:
            print(f"    {col:25s} {coef:+.4f}")

        # Predict test set
        probs = []
        actuals = []
        v2_picks = []
        for r in test_rows:
            pred = predict(model, r)
            probs.append(pred.probability_up_5d)
            actuals.append(1 if float(r.actual_5d) > 0 else 0)
            v2_picks.append(_is_v2_pick(r))

        probs_arr = np.array(probs)
        actuals_arr = np.array(actuals)
        v2_arr = np.array(v2_picks)

        # AUC
        if len(set(actuals)) > 1:
            auc = roc_auc_score(actuals_arr, probs_arr)
        else:
            auc = float("nan")

        baseline = _baseline_up_rate(test_rows)
        v2_mask = v2_arr.astype(bool)
        v2_n = v2_mask.sum()
        v2_hits = actuals_arr[v2_mask].sum() if v2_n > 0 else 0
        v2_rate = v2_hits / v2_n if v2_n > 0 else 0

        print(f"\n  AUC: {auc:.4f}")
        print(f"  Baseline up-rate: {baseline*100:.1f}%")
        print(f"  v2 rule: {v2_n} picks, {v2_rate*100:.1f}% hit rate")

        # Threshold table
        print(f"\n  {'Threshold':>10} {'Picks':>6} {'Hits':>5} {'HitRate':>8} "
              f"{'Baseline':>9} {'Lift':>7} {'v2Rate':>7} {'vsShadow':>9} {'Picks/yr':>9}")
        print(f"  {'':->10} {'':->6} {'':->5} {'':->8} {'':->9} {'':->7} {'':->7} {'':->9} {'':->9}")

        years_span = max(1, (test_end - test_start).days / 365.25)

        for thr in THRESHOLDS:
            mask = probs_arr >= thr
            n = mask.sum()
            hits = actuals_arr[mask].sum() if n > 0 else 0
            rate = hits / n if n > 0 else 0
            lift = rate - baseline
            vs_v2 = rate - v2_rate
            picks_yr = n / years_span

            print(f"  {thr:>10.2f} {n:>6} {int(hits):>5} {rate*100:>7.1f}% "
                  f"{baseline*100:>8.1f}% {lift*100:>+6.1f}pp "
                  f"{v2_rate*100:>6.1f}% {vs_v2*100:>+8.1f}pp {picks_yr:>8.0f}")

        # Overlap analysis
        print(f"\n  OVERLAP ANALYSIS (at each threshold vs v2 rule):")
        print(f"  {'Threshold':>10} {'Both':>6} {'ModelOnly':>10} {'V2Only':>8} "
              f"{'BothHit%':>9} {'MOnlyHit%':>10} {'V2OnlyHit%':>11}")
        print(f"  {'':->10} {'':->6} {'':->10} {'':->8} {'':->9} {'':->10} {'':->11}")

        for thr in THRESHOLDS:
            shadow_mask = probs_arr >= thr
            both = shadow_mask & v2_arr
            model_only = shadow_mask & ~v2_arr
            v2_only = ~shadow_mask & v2_arr

            both_n = both.sum()
            mo_n = model_only.sum()
            vo_n = v2_only.sum()

            both_hits = actuals_arr[both].sum() if both_n > 0 else 0
            mo_hits = actuals_arr[model_only].sum() if mo_n > 0 else 0
            vo_hits = actuals_arr[v2_only].sum() if vo_n > 0 else 0

            both_rate = both_hits / both_n * 100 if both_n > 0 else 0
            mo_rate = mo_hits / mo_n * 100 if mo_n > 0 else 0
            vo_rate = vo_hits / vo_n * 100 if vo_n > 0 else 0

            print(f"  {thr:>10.2f} {both_n:>6} {mo_n:>10} {vo_n:>8} "
                  f"{both_rate:>8.1f}% {mo_rate:>9.1f}% {vo_rate:>10.1f}%")

    # ── Single-feature diagnostic: momentum_20d only ──────────────────────────
    print(f"\n\n{'=' * 100}")
    print("  DIAGNOSTIC: single-feature model (momentum_20d only)")
    print(f"{'=' * 100}")

    DIAG_THRESHOLDS = [0.55, 0.58]

    for fold_name, train_end, test_start, test_end in FOLDS:
        test_rows = [r for r in all_rows
                     if test_start <= r.event_date <= test_end
                     and r.actual_5d is not None]

        if len([r for r in all_rows if r.event_date <= train_end]) < 50:
            continue

        tr = train(all_rows, cutoff_date=test_start, feature_cols=["momentum_20d"])
        model = tr.model

        probs = []
        actuals = []
        for r in test_rows:
            pred = predict(model, r)
            probs.append(pred.probability_up_5d)
            actuals.append(1 if float(r.actual_5d) > 0 else 0)

        probs_arr = np.array(probs)
        actuals_arr = np.array(actuals)

        if len(set(actuals)) > 1:
            auc = roc_auc_score(actuals_arr, probs_arr)
        else:
            auc = float("nan")

        baseline = _baseline_up_rate(test_rows)
        v2_mask = np.array([_is_v2_pick(r) for r in test_rows])
        v2_n = v2_mask.sum()
        v2_hits = actuals_arr[v2_mask].sum() if v2_n > 0 else 0
        v2_rate = v2_hits / v2_n if v2_n > 0 else 0

        print(f"\n  {fold_name}   test: {len(test_rows)} rows   AUC: {auc:.4f}   baseline: {baseline*100:.1f}%   v2: {v2_rate*100:.1f}%")
        print(f"  {'Threshold':>10} {'Picks':>6} {'Hits':>5} {'HitRate':>8} {'Lift':>7}")
        print(f"  {'':->10} {'':->6} {'':->5} {'':->8} {'':->7}")
        for thr in DIAG_THRESHOLDS:
            mask = probs_arr >= thr
            n = mask.sum()
            hits = actuals_arr[mask].sum() if n > 0 else 0
            rate = hits / n if n > 0 else 0
            lift = rate - baseline
            print(f"  {thr:>10.2f} {n:>6} {int(hits):>5} {rate*100:>7.1f}% {lift*100:>+6.1f}pp")

    print(f"\n{'=' * 100}")
    print("Backtest complete.")


if __name__ == "__main__":
    asyncio.run(main())
