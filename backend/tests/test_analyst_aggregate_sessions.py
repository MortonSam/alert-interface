"""Analyst stats count distinct sessions: three downgrades on one day are one observation."""
from datetime import date

from app.scripts.compute_analyst_reactions import MIN_SESSIONS, _aggregate

D = date


def test_same_day_actions_collapse_to_one_observation():
    # SNPS-shaped: three downgrades on 2025-09-10 (-35.84%), three other sessions
    rows = [
        (D(2025, 9, 10), -35.84, -30.64), (D(2025, 9, 10), -35.84, -30.64), (D(2025, 9, 10), -35.84, -30.64),
        (D(2026, 1, 13), -4.05, -2.0), (D(2026, 2, 27), -2.82, 1.0), (D(2025, 12, 8), -0.22, 0.5),
    ]
    out = _aggregate(rows)
    assert out["count"] == 6 and out["sessions"] == 4
    # median of the four session moves, not of six actions
    assert out["median_1d"] == round((-4.05 + -2.82) / 2, 4)
    assert out["sample_5d"] == 4
    assert out["continuation_pct"] == 50.0   # two of four sessions kept their sign


def test_threshold_is_on_sessions_not_actions():
    one_day = [(D(2025, 9, 10), -35.84, None)] * (MIN_SESSIONS + 2)
    out = _aggregate(one_day)
    assert out["count"] == MIN_SESSIONS + 2 and out["sessions"] == 1
    assert out["median_1d"] is None and out["avg_1d"] is None
    spread = [(D(2025, 1, i + 1), -1.0 * i, None) for i in range(MIN_SESSIONS)]
    assert _aggregate(spread)["median_1d"] is not None


def test_empty():
    out = _aggregate([])
    assert out == {"count": 0, "sessions": 0, "avg_1d": None, "median_1d": None,
                   "avg_5d": None, "continuation_pct": None, "sample_5d": 0}
