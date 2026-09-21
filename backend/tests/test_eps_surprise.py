"""EPS surprise: dollars against a near-zero estimate, a capped percent otherwise."""
from app.thresholds import EPS_SURPRISE_DOLLAR_FLOOR, EPS_SURPRISE_PCT_CAP, eps_surprise


def test_ttwo_may_2025_shows_dollars_not_minus_42060_percent():
    # Production row: estimate $0.05, actual -$20.98 (the "-42060%" surprise).
    sp = eps_surprise(0.05, -20.98)
    assert sp.mode == "dollars" and sp.pct is None and sp.display_pct is None
    assert sp.dollars == -21.03


def test_ttwo_may_2024_is_capped_with_exact_dollars_kept():
    # Estimate -$0.98, actual -$17.02: -1636.7%, shown as beyond the cap.
    sp = eps_surprise(-0.98, -17.02)
    assert sp.mode == "pct" and sp.pct == -1636.7 and sp.capped
    assert sp.display_pct == -EPS_SURPRISE_PCT_CAP
    assert sp.dollars == -16.04


def test_ordinary_surprise_is_unchanged():
    sp = eps_surprise(1.09, 1.30)
    assert sp.mode == "pct" and sp.pct == 19.3 and sp.display_pct == 19.3 and not sp.capped


def test_floor_boundary_and_missing_values():
    assert eps_surprise(EPS_SURPRISE_DOLLAR_FLOOR, 0.2).mode == "pct"
    assert eps_surprise(-(EPS_SURPRISE_DOLLAR_FLOOR - 0.001), 0.2).mode == "dollars"
    assert eps_surprise(0.0, 0.2).mode == "dollars"          # no division by zero
    assert eps_surprise(None, 0.2) is None and eps_surprise(0.5, None) is None
