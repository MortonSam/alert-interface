"""The read-only deal detector (scripts/list_pinned_tickers): collapsed volatility, a pinned price, a round level above it."""
import numpy as np
import pytest

from app.scripts import list_pinned_tickers as P


def test_round_levels_step_with_price():
    assert P.round_gap(14.93) == (15.0, pytest.approx(0.4667, abs=1e-3))
    assert P.round_gap(72.45)[0] == 75.0 and P.round_gap(171.34)[0] == 175.0 and P.round_gap(512.0)[0] == 520.0
    assert P.round_gap(15.0) == (15.0, 0.0)


def test_a_deal_pinned_series_is_flagged_and_a_normal_one_is_not():
    rng = np.random.default_rng(0)
    normal = 20 * np.exp(np.cumsum(rng.normal(0, 0.015, 260)))
    pinned = np.concatenate([normal[:230], 14.9 + rng.normal(0, 0.01, 30)])
    a = P.assess(pinned)
    assert a["collapsed"] and a["pinned"] and a["under_round"] and a["round_level"] == 15.0
    b = P.assess(normal)
    assert not (b["collapsed"] and b["pinned"])
    assert P.assess(normal[:50]) is None
