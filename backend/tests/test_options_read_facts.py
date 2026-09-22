"""The prompt strings are formatted from the numeric fact block the page also renders."""
from app.services.options_read_gate import FACT_VALUE_KEYS, format_facts

VALUES = {
    "current_price": 339.07, "price_as_of": "2026-09-21T17:59:00+00:00", "chain_date": "2026-09-18",
    "expected_move_pct": 0.0828, "expected_move_dollars": 28.08, "implied_range_low": 311.16, "implied_range_high": 367.31,
    "expiration_used": "2026-10-16", "days_to_expiration": 25, "atm_strike": 340.0, "atm_iv": 0.2463, "atm_iv_as_of": "2026-09-21",
    "next_earnings_date": "2026-10-29", "expiration_spans_earnings": False, "days_exp_past_earnings": None,
    "rv_20d": 0.2145, "rv_rank": 40.3, "rv_percentile": 38.9, "rv_min_1y": 0.0964, "rv_max_1y": 0.3894, "rv_sample_days": 252,
    "rv_reason": None, "rv_as_of": "2026-09-21",
    "iv_rv_spread_pp": 3.2, "avg_earnings_1d_move_pct": 3.4, "earnings_sample_size": 20,
}


def test_every_prompt_number_comes_from_the_block():
    f = format_facts("AAPL", "Apple Inc.", VALUES)
    assert f["current_price"] == "$339.07"
    assert f["implied_range"] == "$311.16 - $367.31"
    assert f["expected_move_pct"] == "±8.3%" and f["expected_move_dollars"] == "±$28.08"
    assert f["atm_iv"] == "24.6%" and f["realized_vol_20d"] == "21.4%" and f["iv_rv_spread"] == "+3.2pp"
    assert f["rv_rank"] == "40.3" and f["rv_1yr_range"] == "9.6% - 38.9%"
    assert f["avg_earnings_1d_move"] == "±3.4%" and f["earnings_sample_size"] == "20"


def test_changing_the_block_changes_the_prompt():
    moved = dict(VALUES, implied_range_low=310.91, implied_range_high=367.06)
    assert format_facts("AAPL", "Apple Inc.", moved)["implied_range"] == "$310.91 - $367.06"


def test_missing_values_read_unavailable_and_the_key_list_is_complete():
    f = format_facts("X", "X Co", {})
    for k in ("current_price", "implied_range", "atm_iv", "realized_vol_20d", "iv_rv_spread", "earnings_sample_size"):
        assert f[k] == "(unavailable)", k
    assert set(VALUES) == set(FACT_VALUE_KEYS)
