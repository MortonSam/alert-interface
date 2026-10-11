"""Build a Trade never dead-ends: when the options price a bigger move than the stock usually makes (Ivy's own rule, ivy_v2.
vol_gate_trips), the customer's draft is a cheaper defined-risk spread in the direction they chose, built from the same checked
strikes with no AI call; Ivy's refusal rule for her own ledger is unchanged."""
import asyncio
from datetime import date, timedelta

import pytest

from app.routers import thesis as T
from app.services import ivy_v2

SPOT = 300.0
CALLS = [{"strike": k, "bid": m - 0.1, "ask": m + 0.1, "lastPrice": m, "impliedVolatility": 0.6}
         for k, m in [(280, 26.0), (290, 19.0), (300, 13.0), (310, 8.5), (320, 5.2), (330, 3.0), (340, 1.7)]]
PUTS = [{"strike": k, "bid": m - 0.1, "ask": m + 0.1, "lastPrice": m, "impliedVolatility": 0.6}
        for k, m in [(260, 1.6), (270, 2.8), (280, 4.9), (290, 8.0), (300, 12.6), (310, 18.4), (320, 25.5)]]
PREMIUM = {"implied_pct": 13.4, "usual_pct": 6.5, "cap": 1.2, "expensive": True}


def test_the_rule_is_ivys_and_one_place():
    assert ivy_v2.vol_gate_trips(13.4, 6.5) and not ivy_v2.vol_gate_trips(7.0, 6.5) and not ivy_v2.vol_gate_trips(13.4, 0)
    assert ivy_v2.vol_gate_trips(6.5 * ivy_v2.IV_PREMIUM_CAP + 0.01, 6.5) and not ivy_v2.vol_gate_trips(6.5 * ivy_v2.IV_PREMIUM_CAP, 6.5)
    import inspect
    assert "vol_gate_trips(implied_move, expected)" in inspect.getsource(ivy_v2.decide)          # her own pick reads the same rule


def rows(raw):
    return [{"strike": c["strike"], "mid": c["lastPrice"]} for c in raw]


def test_a_bull_call_spread_from_the_money_to_past_the_usual_move():
    s = T.build_defined_risk_spread("bullish", rows(CALLS), SPOT, 6.5)
    assert (s["long_strike"], s["short_strike"], s["net_debit"], s["outright_mid"]) == (300, 320, 7.8, 13.0)   # 300 × 1.065 = 319.5 → 320
    assert s["net_debit"] < s["outright_mid"] and s["net_debit"] < s["width"]


def test_a_bear_put_spread_the_other_way():
    s = T.build_defined_risk_spread("bearish", rows(PUTS), SPOT, 6.5)
    assert (s["long_strike"], s["short_strike"], s["net_debit"], s["outright_mid"]) == (300, 280, 7.7, 12.6)   # 300 × 0.935 = 280.5 → 280


def test_no_spread_when_the_prices_cannot_make_one():
    assert T.build_defined_risk_spread("bullish", rows(CALLS)[:1], SPOT, 6.5) is None
    bad = [{"strike": 300, "mid": 5.0}, {"strike": 320, "mid": 6.0}]                     # a debit that is not positive
    assert T.build_defined_risk_spread("bullish", bad, SPOT, 6.5) is None


def _data():
    earnings = date.today() + timedelta(days=5)
    exp = earnings + timedelta(days=20)
    return {"sym": "ZZDR", "draft_spot": SPOT, "current_price": SPOT, "earnings_str": earnings.isoformat(), "hist_avg": 0.05, "hist_max": 0.12,
            "hist_min": 0.01, "hist_sample": 12, "beats": [], "ce_misses": [], "beat_rate": 75.0, "bbd_rate": 30.0, "avg_1d_on_beat": None,
            "median_1d_on_beat": None, "avg_1d_on_miss": None, "median_1d_on_miss": None, "beat_cont_pct": None, "beat_5d_n": 0,
            "miss_cont_pct": None, "miss_5d_n": 0, "magnitude_trend": None, "analyst_row": None, "chosen_exp": exp.isoformat(),
            "days_to_exp": 25, "calls_raw": CALLS, "puts_raw": PUTS, "atm_strike": 300.0, "expected_move_pct": 0.134,
            "expected_move_dollars": 40.2, "implied_range_low": 259.8, "implied_range_high": 340.2, "atm_iv": 0.6, "current_rv": 0.3,
            "rv_rank": 70.0, "iv_rv_spread_pp": 30.0, "vol_regime": "iv_rich", "chain_last_trade": date.today().isoformat(),
            "price_as_of": None}


class NoAI:
    def __init__(self, *a, **k):
        raise AssertionError("the cheaper draft makes no AI call")


def test_the_draft_path_returns_the_cheaper_spread_with_its_comparison_and_no_ai_call(monkeypatch):
    monkeypatch.setattr(T, "AnthropicClient", NoAI)
    for direction, legs in [("bullish", (300, 320)), ("bearish", (300, 280))]:
        d = asyncio.run(T._run_draft_generation(_data(), direction, "moderate", premium=PREMIUM))
        assert (d.suggested_strike, d.suggested_spread_strike) == legs and d.model_used == "deterministic"
        assert d.options_expensive["implied_pct"] == 13.4 and d.options_expensive["usual_pct"] == 6.5
        assert d.options_expensive["outright_strike"] == 300
        assert {r["strike"] for r in d.fact_block["primary_strikes"]} >= set(legs)        # the page prices both legs from the same rows
        assert "13.4% move" in d.reasoning and "6.5%" in d.reasoning
    # the same checks as every draft still apply: stale options refuse before any spread is built
    stale = {**_data(), "chain_last_trade": (date.today() - timedelta(days=10)).isoformat()}
    with pytest.raises(Exception):
        asyncio.run(T._run_draft_generation(stale, "bullish", "moderate", premium=PREMIUM))


def test_options_that_are_not_expensive_keep_the_usual_draft(monkeypatch):
    monkeypatch.setattr(T, "AnthropicClient", NoAI)
    with pytest.raises(AssertionError, match="no AI call"):                               # it went on to the AI draft
        asyncio.run(T._run_draft_generation(_data(), "bullish", "moderate", premium={**PREMIUM, "expensive": False}))


def test_a_split_stocks_adjusted_contracts_never_price_a_draft():
    # PANW on Oct 9, 2026: Intrinio lists the adjusted contracts beside the standard ones at the same strikes
    calls = [{"strike": 360.0, "bid": 71.75, "ask": 78.75, "lastPrice": 79.56, "impliedVolatility": 0.54},
             {"strike": 360.0, "bid": 607.45, "ask": 611.5, "lastPrice": 482.2, "impliedVolatility": 105526808639.2},
             {"strike": 420.0, "bid": 38.75, "ask": 41.10, "lastPrice": 42.85, "impliedVolatility": 0.53},
             {"strike": 420.0, "bid": 547.8, "ask": 552.0, "lastPrice": None, "impliedVolatility": 1532.19},
             {"strike": 460.0, "bid": 24.0, "ask": 26.4, "lastPrice": 25.0, "impliedVolatility": 0.52}]
    _, rows = T._build_strike_lines(calls, 420.0, 418.78)
    assert [(r["strike"], r["mid"]) for r in rows] == [(360.0, 75.25), (420.0, 39.92), (460.0, 25.2)]
    s = T.build_defined_risk_spread("bullish", rows, 418.78, 9.37)
    assert (s["long_strike"], s["short_strike"], s["net_debit"]) == (360.0, 460.0, 50.05)
