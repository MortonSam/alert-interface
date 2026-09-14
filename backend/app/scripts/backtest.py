"""Backtest harness for Ivy v1 lean system.

Reads the earnings_features table and produces a plain-text report
measuring hit rates, bias, decision quality, and feature coverage.

CLI
---
    python -m app.scripts.backtest
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections import defaultdict
from datetime import date

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.earnings_feature import EarningsFeature

TRAIN_CUTOFF = date(2025, 1, 1)
CASE_STUDY_SYMBOLS = ["ULTA", "DLTR", "WDAY", "ADSK", "DECK"]


# ── Formatting helpers ──────────────────────────────────────────────────────

def _pct(n: int, total: int) -> str:
    if total == 0:
        return "  n/a"
    return f"{n / total * 100:5.1f}%"


def _avg(vals: list[float]) -> str:
    if not vals:
        return "    n/a"
    return f"{sum(vals) / len(vals):+7.2f}%"


def _header(title: str) -> str:
    return f"\n{'=' * 80}\n  {title}\n{'=' * 80}"


def _subheader(title: str) -> str:
    return f"\n--- {title} ---"


def _flag(train_val: float | None, test_val: float | None) -> str:
    """Return ' *' if train and test disagree in direction."""
    if train_val is None or test_val is None:
        return ""
    if (train_val > 0) != (test_val > 0) and train_val != 0 and test_val != 0:
        return " *"
    return ""


def _quintile_edges(vals: list[float]) -> list[float]:
    """Return 4 edges for 5 quintile buckets."""
    s = sorted(vals)
    n = len(s)
    return [s[int(n * p)] for p in [0.2, 0.4, 0.6, 0.8]]


def _quintile_label(edges: list[float], idx: int) -> str:
    """Label for quintile bucket."""
    if idx == 0:
        return f"Q1 (<{edges[0]:.1f})"
    elif idx == 4:
        return f"Q5 (>={edges[3]:.1f})"
    else:
        return f"Q{idx+1} [{edges[idx-1]:.1f},{edges[idx]:.1f})"


def _quintile_idx(val: float, edges: list[float]) -> int:
    """Return 0-4 quintile index."""
    for i, e in enumerate(edges):
        if val < e:
            return i
    return 4


# ── Section 1: Decision distribution ────────────────────────────────────────

def _report_distribution(rows: list, label: str) -> None:
    total = len(rows)
    by_dec = defaultdict(int)
    for r in rows:
        by_dec[r.decision or "null"] += 1

    print(_subheader(f"Decision Distribution ({label}, n={total})"))
    print(f"  {'Decision':15s} {'Count':>6s} {'Pct':>7s}")
    print(f"  {'-'*15} {'-'*6} {'-'*7}")
    for dec in ["bullish", "bearish", "mixed", "null"]:
        cnt = by_dec.get(dec, 0)
        print(f"  {dec:15s} {cnt:6d} {_pct(cnt, total):>7s}")


# ── Section 2: Hit rates (1d + 5d) ─────────────────────────────────────────

def _report_hit_rates(train: list, test: list) -> None:
    for horizon, attr in [("1d", "actual_1d"), ("5d", "actual_5d")]:
        for rows, label in [(train, "Train"), (test, "Test")]:
            with_data = [r for r in rows if getattr(r, attr) is not None]
            positive = sum(1 for r in with_data if float(getattr(r, attr)) > 0)
            base = positive / len(with_data) * 100 if with_data else 0

            print(_subheader(f"Hit Rates {horizon} ({label}, n={len(with_data)})"))
            print(f"  Base rate ({attr} > 0): {base:.1f}%")
            print()
            print(f"  {'Decision':15s} {'Hits':>5s} {'Total':>6s} {'Hit%':>7s} {'vs Base':>8s}")
            print(f"  {'-'*15} {'-'*5} {'-'*6} {'-'*7} {'-'*8}")

            for dec, check_fn in [
                ("bullish", lambda x: float(x) > 0),
                ("bearish", lambda x: float(x) < 0),
            ]:
                subset = [r for r in with_data if r.decision == dec]
                if not subset:
                    print(f"  {dec:15s} {'':>5s} {'0':>6s}")
                    continue
                hits = sum(1 for r in subset if check_fn(getattr(r, attr)))
                hit_pct = hits / len(subset) * 100
                diff = hit_pct - base if dec == "bullish" else hit_pct - (100 - base)
                print(f"  {dec:15s} {hits:5d} {len(subset):6d} {hit_pct:6.1f}% {diff:+7.1f}pp")


# ── Section 3: Mean move by decision (already has 1d/3d/5d) ────────────────

def _report_mean_move(rows: list, label: str) -> None:
    print(_subheader(f"Mean Move by Decision ({label})"))
    print(f"  {'Decision':15s} {'n':>5s} {'avg_1d':>8s} {'avg_3d':>8s} {'avg_5d':>8s}")
    print(f"  {'-'*15} {'-'*5} {'-'*8} {'-'*8} {'-'*8}")

    for dec in ["bullish", "bearish", "mixed"]:
        subset = [r for r in rows if r.decision == dec]
        v1d = [float(r.actual_1d) for r in subset if r.actual_1d is not None]
        v3d = [float(r.actual_3d) for r in subset if r.actual_3d is not None]
        v5d = [float(r.actual_5d) for r in subset if r.actual_5d is not None]
        print(f"  {dec:15s} {len(subset):5d} {_avg(v1d):>8s} {_avg(v3d):>8s} {_avg(v5d):>8s}")


# ── Section 4: Individual lean accuracy (1d + 5d) ──────────────────────────

def _report_individual_lean(rows: list, label: str) -> None:
    print(_subheader(f"Individual Lean Accuracy ({label})"))
    print(f"  {'Lean':20s} {'Dir':>8s} {'n':>5s} {'1d_acc':>7s} {'5d_acc':>7s}")
    print(f"  {'-'*20} {'-'*8} {'-'*5} {'-'*7} {'-'*7}")

    with_data = [r for r in rows if r.actual_1d is not None and r.actual_5d is not None]

    for lean_col, lean_name in [
        ("lean_earnings", "Earnings"),
        ("lean_analyst", "Analyst"),
        ("lean_momentum", "Momentum"),
    ]:
        for direction, check_1d, check_5d in [
            ("bullish", lambda x: float(x) > 0, lambda x: float(x) > 0),
            ("bearish", lambda x: float(x) < 0, lambda x: float(x) < 0),
        ]:
            subset = [r for r in with_data if getattr(r, lean_col) == direction]
            if not subset:
                continue
            hits_1d = sum(1 for r in subset if check_1d(r.actual_1d))
            hits_5d = sum(1 for r in subset if check_5d(r.actual_5d))
            acc_1d = hits_1d / len(subset) * 100
            acc_5d = hits_5d / len(subset) * 100
            print(f"  {lean_name:20s} {direction:>8s} {len(subset):5d} {acc_1d:6.1f}% {acc_5d:6.1f}%")


# ── Section 5: Bucketed by weighted_1d (1d + 5d) ───────────────────────────

def _report_bucketed(rows: list, label: str) -> None:
    print(_subheader(f"Bucketed by weighted_1d ({label})"))

    with_data = [r for r in rows if r.weighted_1d is not None and r.actual_1d is not None and r.actual_5d is not None]
    buckets = [
        ("< -2%", lambda w: float(w) < -2),
        ("-2% to -0.5%", lambda w: -2 <= float(w) < -0.5),
        ("-0.5% to +0.5%", lambda w: -0.5 <= float(w) <= 0.5),
        ("+0.5% to +2%", lambda w: 0.5 < float(w) <= 2),
        ("> +2%", lambda w: float(w) > 2),
    ]

    print(f"  {'Bucket':20s} {'n':>5s} {'1d>0%':>7s} {'avg_1d':>8s} {'5d>0%':>7s} {'avg_5d':>8s}")
    print(f"  {'-'*20} {'-'*5} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")
    for name, fn in buckets:
        subset = [r for r in with_data if fn(r.weighted_1d)]
        if not subset:
            print(f"  {name:20s} {'0':>5s}")
            continue
        pos_1d = sum(1 for r in subset if float(r.actual_1d) > 0)
        pos_5d = sum(1 for r in subset if float(r.actual_5d) > 0)
        v1d = [float(r.actual_1d) for r in subset]
        v5d = [float(r.actual_5d) for r in subset]
        print(f"  {name:20s} {len(subset):5d} {_pct(pos_1d, len(subset)):>7s} {_avg(v1d):>8s} "
              f"{_pct(pos_5d, len(subset)):>7s} {_avg(v5d):>8s}")


# ── Section 6: Feature coverage ────────────────────────────────────────────

def _report_coverage(rows: list) -> None:
    print(_subheader("Feature Coverage (all events)"))
    total = len(rows)
    cols = [
        "beat_rate", "median_1d_beat", "median_1d_miss", "weighted_1d",
        "buy_share_latest", "buy_share_60d_ago", "analyst_delta",
        "momentum_20d", "prior_avg_abs_1d", "analyst_net_90d",
        "atm_iv", "actual_1d", "actual_3d", "actual_5d",
    ]
    print(f"  {'Feature':25s} {'Non-null':>8s} {'Pct':>7s}")
    print(f"  {'-'*25} {'-'*8} {'-'*7}")
    for col in cols:
        non_null = sum(1 for r in rows if getattr(r, col) is not None)
        print(f"  {col:25s} {non_null:8d} {_pct(non_null, total):>7s}")


# ── Section 7: Case studies ────────────────────────────────────────────────

def _report_case_studies(rows: list) -> None:
    print(_subheader("Case Studies"))

    for sym in CASE_STUDY_SYMBOLS:
        events = sorted(
            [r for r in rows if r.symbol == sym],
            key=lambda r: r.event_date,
        )
        if not events:
            print(f"\n  {sym}: no events found")
            continue

        print(f"\n  {sym} ({len(events)} events)")
        print(f"  {'Date':>12s} {'w1d':>7s} {'E':>4s} {'A':>4s} {'M':>4s} "
              f"{'Dec':>8s} {'1d':>7s} {'5d':>7s} {'pavg':>6s} {'an90':>5s} {'Outcome':>8s}")
        print(f"  {'-'*12} {'-'*7} {'-'*4} {'-'*4} {'-'*4} "
              f"{'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*5} {'-'*8}")

        for r in events:
            w1d = f"{float(r.weighted_1d):+.1f}" if r.weighted_1d is not None else "  n/a"
            a1d = f"{float(r.actual_1d):+.1f}" if r.actual_1d is not None else "  n/a"
            a5d = f"{float(r.actual_5d):+.1f}" if r.actual_5d is not None else "  n/a"
            pavg = f"{float(r.prior_avg_abs_1d):.1f}" if r.prior_avg_abs_1d is not None else " n/a"
            an90 = f"{r.analyst_net_90d:+d}" if r.analyst_net_90d is not None else " n/a"

            def _abbr(lean: str | None) -> str:
                if lean is None:
                    return "  -"
                return {"bullish": "  B", "bearish": " Be", "neutral": "  N"}.get(lean, "  ?")

            print(f"  {str(r.event_date):>12s} {w1d:>7s} {_abbr(r.lean_earnings):>4s} "
                  f"{_abbr(r.lean_analyst):>4s} {_abbr(r.lean_momentum):>4s} "
                  f"{(r.decision or 'n/a'):>8s} {a1d:>7s} {a5d:>7s} {pavg:>6s} {an90:>5s} "
                  f"{(r.outcome or 'UNK'):>8s}")


# ── NEW Section: Magnitude predictability ───────────────────────────────────

def _report_magnitude(train: list, test: list) -> None:
    print(_header("Magnitude Predictability"))
    print("  Does prior avg |move| predict realized |move|?")

    for rows, label in [(train, "Train"), (test, "Test")]:
        with_data = [
            r for r in rows
            if r.prior_avg_abs_1d is not None and r.actual_1d is not None
        ]
        if len(with_data) < 20:
            print(f"\n  {label}: insufficient data ({len(with_data)} rows)")
            continue

        priors = [float(r.prior_avg_abs_1d) for r in with_data]
        realized = [abs(float(r.actual_1d)) for r in with_data]

        # Correlation
        n = len(priors)
        mean_p = sum(priors) / n
        mean_r = sum(realized) / n
        cov = sum((p - mean_p) * (r - mean_r) for p, r in zip(priors, realized)) / n
        std_p = (sum((p - mean_p) ** 2 for p in priors) / n) ** 0.5
        std_r = (sum((r - mean_r) ** 2 for r in realized) / n) ** 0.5
        corr = cov / (std_p * std_r) if std_p > 0 and std_r > 0 else 0

        # Overpriced rate
        overpriced = sum(1 for p, r in zip(priors, realized) if r < p)
        overpriced_pct = overpriced / n * 100

        print(_subheader(f"Magnitude ({label}, n={n})"))
        print(f"  Correlation(prior_avg_|1d|, realized_|1d|): {corr:.3f}")
        print(f"  Share with realized < prior avg: {overpriced_pct:.1f}% ({overpriced}/{n})")

        # Quintile table
        edges = _quintile_edges(priors)
        print(f"\n  {'Quintile':25s} {'n':>5s} {'med_|1d|':>8s} {'avg_|1d|':>8s}")
        print(f"  {'-'*25} {'-'*5} {'-'*8} {'-'*8}")

        for qi in range(5):
            bucket = [(p, r) for p, r in zip(priors, realized) if _quintile_idx(p, edges) == qi]
            if not bucket:
                continue
            rs = [r for _, r in bucket]
            med = statistics.median(rs)
            avg = sum(rs) / len(rs)
            print(f"  {_quintile_label(edges, qi):25s} {len(bucket):5d} {med:7.2f}% {avg:7.2f}%")


# ── NEW Section: Analyst net 90d ────────────────────────────────────────────

def _report_analyst_net(train: list, test: list) -> None:
    print(_header("Analyst Events Feature (analyst_net_90d)"))

    all_rows = train + test
    with_data = [r for r in all_rows if r.analyst_net_90d is not None]
    nonzero = [r for r in with_data if r.analyst_net_90d != 0]
    print(f"  Coverage: {len(with_data)}/{len(all_rows)} ({_pct(len(with_data), len(all_rows)).strip()})")
    print(f"  Non-zero: {len(nonzero)}/{len(with_data)} ({_pct(len(nonzero), len(with_data)).strip()})")

    buckets = [
        ("<= -2", lambda x: x <= -2),
        ("-1", lambda x: x == -1),
        ("0", lambda x: x == 0),
        ("+1", lambda x: x == 1),
        (">= +2", lambda x: x >= 2),
    ]

    # Collect per-split results for flagging
    results_1d: dict[str, dict[str, float | None]] = defaultdict(dict)
    results_5d: dict[str, dict[str, float | None]] = defaultdict(dict)

    for rows, label in [(train, "Train"), (test, "Test")]:
        with_data = [r for r in rows if r.analyst_net_90d is not None
                     and r.actual_1d is not None and r.actual_5d is not None]
        if not with_data:
            print(f"\n  {label}: no data")
            continue

        print(_subheader(f"Analyst net_90d Hit Rates ({label})"))
        print(f"  {'Bucket':10s} {'n':>5s} {'up_1d%':>7s} {'avg_1d':>8s} {'up_5d%':>7s} {'avg_5d':>8s}")
        print(f"  {'-'*10} {'-'*5} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")

        for bname, bfn in buckets:
            subset = [r for r in with_data if bfn(r.analyst_net_90d)]
            if not subset:
                print(f"  {bname:10s} {'0':>5s}")
                results_1d[bname][label] = None
                results_5d[bname][label] = None
                continue
            up_1d = sum(1 for r in subset if float(r.actual_1d) > 0)
            up_5d = sum(1 for r in subset if float(r.actual_5d) > 0)
            v1d = [float(r.actual_1d) for r in subset]
            v5d = [float(r.actual_5d) for r in subset]
            up_1d_pct = up_1d / len(subset) * 100
            up_5d_pct = up_5d / len(subset) * 100
            results_1d[bname][label] = up_1d_pct - 50
            results_5d[bname][label] = up_5d_pct - 50
            print(f"  {bname:10s} {len(subset):5d} {up_1d_pct:6.1f}% {_avg(v1d):>8s} "
                  f"{up_5d_pct:6.1f}% {_avg(v5d):>8s}")

    # Flag disagreements
    flags = []
    for bname in [b[0] for b in buckets]:
        for res, hz in [(results_1d, "1d"), (results_5d, "5d")]:
            tr = res.get(bname, {}).get("Train")
            te = res.get(bname, {}).get("Test")
            if tr is not None and te is not None and tr != 0 and te != 0:
                if (tr > 0) != (te > 0):
                    flags.append(f"    analyst_net {bname} {hz}: Train {'>' if tr > 0 else '<'}50%, Test {'>' if te > 0 else '<'}50%")
    if flags:
        print(f"\n  * Direction disagreements (noise):")
        for f in flags:
            print(f)


# ── NEW Section: Earnings crosstab ──────────────────────────────────────────

def _report_earnings_crosstab(train: list, test: list) -> None:
    print(_header("Earnings Crosstab: beat_rate Q x up_after_beat_rate Q -> up_5d%"))
    print("  up_after_beat_rate = median_1d_beat (positive = stock usually goes up on beat)")

    for rows, label in [(train, "Train"), (test, "Test")]:
        # Need beat_rate, median_1d_beat, and actual_5d
        with_data = [r for r in rows
                     if r.beat_rate is not None
                     and r.median_1d_beat is not None
                     and r.actual_5d is not None]
        if len(with_data) < 50:
            print(f"\n  {label}: insufficient data ({len(with_data)} rows)")
            continue

        br_vals = [float(r.beat_rate) for r in with_data]
        ub_vals = [float(r.median_1d_beat) for r in with_data]

        br_edges = _quintile_edges(br_vals)
        ub_edges = _quintile_edges(ub_vals)

        print(_subheader(f"Crosstab ({label}, n={len(with_data)})"))
        print(f"  Rows = beat_rate quintile, Cols = median_1d_beat quintile")
        print(f"  Cell = up_5d% (n)")
        print()

        # Column headers
        col_labels = [_quintile_label(ub_edges, i) for i in range(5)]
        hdr = f"  {'beat_rate Q':>20s}"
        for cl in col_labels:
            hdr += f" {cl:>16s}"
        print(hdr)
        print(f"  {'-'*20}" + f" {'-'*16}" * 5)

        hot_cells = []
        for bri in range(5):
            row_label = _quintile_label(br_edges, bri)
            cells = []
            for ubi in range(5):
                cell = [r for r in with_data
                        if _quintile_idx(float(r.beat_rate), br_edges) == bri
                        and _quintile_idx(float(r.median_1d_beat), ub_edges) == ubi]
                if not cell:
                    cells.append(f"{'- (0)':>16s}")
                else:
                    up5 = sum(1 for r in cell if float(r.actual_5d) > 0)
                    pct = up5 / len(cell) * 100
                    cells.append(f"{pct:5.1f}% ({len(cell):>3d})")
                    if pct >= 58 and len(cell) >= 100:
                        hot_cells.append((row_label, col_labels[ubi], pct, len(cell)))
            print(f"  {row_label:>20s} " + " ".join(f"{c:>16s}" for c in cells))

        if hot_cells:
            print(f"\n  ** Cells >= 58% with n >= 100:")
            for rl, cl, pct, n in hot_cells:
                print(f"     {rl} x {cl}: {pct:.1f}% (n={n})")
        else:
            print(f"\n  No cells clear 58% with n >= 100")


# ── NEW Section: Momentum at earnings ───────────────────────────────────────

def _report_momentum_at_earnings(train: list, test: list) -> None:
    print(_header("Momentum at Earnings: up_1d & up_5d by momentum_20d"))

    momentum_buckets = [
        ("< -10%", lambda m: float(m) < -10),
        ("-10% to -5%", lambda m: -10 <= float(m) < -5),
        ("-5% to 0%", lambda m: -5 <= float(m) < 0),
        ("0% to +5%", lambda m: 0 <= float(m) < 5),
        ("+5% to +10%", lambda m: 5 <= float(m) < 10),
        ("> +10%", lambda m: float(m) >= 10),
    ]

    results_1d: dict[str, dict[str, float | None]] = defaultdict(dict)
    results_5d: dict[str, dict[str, float | None]] = defaultdict(dict)

    for rows, label in [(train, "Train"), (test, "Test")]:
        with_data = [r for r in rows
                     if r.momentum_20d is not None
                     and r.actual_1d is not None
                     and r.actual_5d is not None]
        if not with_data:
            print(f"\n  {label}: no data")
            continue

        print(_subheader(f"Momentum Buckets ({label}, n={len(with_data)})"))
        print(f"  {'Bucket':15s} {'n':>5s} {'up_1d%':>7s} {'avg_1d':>8s} {'up_5d%':>7s} {'avg_5d':>8s}")
        print(f"  {'-'*15} {'-'*5} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")

        for bname, bfn in momentum_buckets:
            subset = [r for r in with_data if bfn(r.momentum_20d)]
            if not subset:
                print(f"  {bname:15s} {'0':>5s}")
                results_1d[bname][label] = None
                results_5d[bname][label] = None
                continue
            up_1d = sum(1 for r in subset if float(r.actual_1d) > 0)
            up_5d = sum(1 for r in subset if float(r.actual_5d) > 0)
            v1d = [float(r.actual_1d) for r in subset]
            v5d = [float(r.actual_5d) for r in subset]
            up_1d_pct = up_1d / len(subset) * 100
            up_5d_pct = up_5d / len(subset) * 100
            results_1d[bname][label] = up_1d_pct - 50
            results_5d[bname][label] = up_5d_pct - 50
            print(f"  {bname:15s} {len(subset):5d} {up_1d_pct:6.1f}% {_avg(v1d):>8s} "
                  f"{up_5d_pct:6.1f}% {_avg(v5d):>8s}")

    # Flag disagreements
    flags = []
    for bname in [b[0] for b in momentum_buckets]:
        for res, hz in [(results_1d, "1d"), (results_5d, "5d")]:
            tr = res.get(bname, {}).get("Train")
            te = res.get(bname, {}).get("Test")
            if tr is not None and te is not None and tr != 0 and te != 0:
                if (tr > 0) != (te > 0):
                    flags.append(f"    momentum {bname} {hz}: Train {'>' if tr > 0 else '<'}50%, Test {'>' if te > 0 else '<'}50%")
    if flags:
        print(f"\n  * Direction disagreements (noise):")
        for f in flags:
            print(f)
    else:
        print(f"\n  No direction disagreements between train/test")


# ── Main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    async with ScriptSessionLocal() as session:
        result = await session.execute(
            select(EarningsFeature).order_by(
                EarningsFeature.symbol, EarningsFeature.event_date
            )
        )
        all_rows = result.scalars().all()

    if not all_rows:
        print("No rows in earnings_features. Run build_features first.")
        return

    train = [r for r in all_rows if r.event_date < TRAIN_CUTOFF]
    test = [r for r in all_rows if r.event_date >= TRAIN_CUTOFF]

    print(_header("Ivy v1 Backtest Report (Stage 1b)"))
    print(f"\n  Total events: {len(all_rows)}")
    print(f"  Train (before {TRAIN_CUTOFF}): {len(train)}")
    print(f"  Test  (from {TRAIN_CUTOFF}):  {len(test)}")

    # ── Original sections (per split) ───────────────────────────────────────
    for split_rows, label in [(train, "Train"), (test, "Test")]:
        if not split_rows:
            print(f"\n  {label}: no events")
            continue
        print(_header(f"{label} Split"))
        _report_distribution(split_rows, label)
        _report_mean_move(split_rows, label)
        _report_individual_lean(split_rows, label)
        _report_bucketed(split_rows, label)

    # ── Hit rates (1d + 5d, train and test together for comparison) ─────────
    print(_header("Hit Rates (1d + 5d)"))
    _report_hit_rates(train, test)

    # ── New analyses ────────────────────────────────────────────────────────
    _report_magnitude(train, test)
    _report_analyst_net(train, test)
    _report_earnings_crosstab(train, test)
    _report_momentum_at_earnings(train, test)

    # ── Coverage + case studies (all data) ──────────────────────────────────
    print(_header("Coverage & Case Studies"))
    _report_coverage(all_rows)
    _report_case_studies(all_rows)

    print(f"\n{'=' * 80}")
    print("  End of report")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
