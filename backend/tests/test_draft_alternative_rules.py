"""The budget alternative by rules (services/draft_rules.alternative; Sam, 2026-11-06: no part of drafting uses the model)."""
from app.services import draft_copy as copy
from app.services import draft_rules as R

# calls around a $100 stock: strike, mid
CALLS = [{"strike": k, "mid": m} for k, m in [(95, 7.4), (100, 4.2), (105, 2.1), (110, 0.95), (115, 0.4), (120, 0.15)]]
PUTS = [{"strike": k, "mid": m} for k, m in [(80, 0.2), (85, 0.5), (90, 1.2), (95, 2.5), (100, 4.6), (105, 7.9)]]


def test_a_spread_from_the_drafts_strike_is_tried_first_and_the_widest_that_fits_wins():
    a = R.alternative("bullish", CALLS, 100.0, 300, best_long=100, target=112)
    assert isinstance(a, R.Alternative) and a.structure == "spread"
    assert (a.long_strike, a.short_strike) == (100, 105) and a.cost == 210.0          # 100/110 costs $325, over the budget
    a = R.alternative("bullish", CALLS, 100.0, 400, best_long=100, target=112)
    assert (a.long_strike, a.short_strike, a.cost) == (100, 115, 380.0)                # 115 is the first strike at the target
    a = R.alternative("bullish", CALLS, 100.0, 400, best_long=100, target=104)       # never past the first strike at the target
    assert (a.long_strike, a.short_strike) == (100, 105)
    a = R.alternative("bullish", CALLS, 100.0, 120, best_long=100, target=112)       # no spread from 100 fits: the next strike out
    assert (a.structure, a.long_strike, a.short_strike, a.cost) == ("spread", 105, 110, 115.0)


def test_a_single_option_further_out_when_no_spread_fits_and_never_a_lottery_ticket():
    flat = [{"strike": 100, "mid": 4.2}, {"strike": 105, "mid": 2.1}, {"strike": 110, "mid": 0.95}]
    a = R.alternative("bullish", flat[:1] + flat[1:], 100.0, 100, best_long=100, target=None)
    assert isinstance(a, R.Alternative) and a.structure == "long" and a.long_strike == 110 and a.cost == 95.0
    none = R.alternative("bullish", CALLS, 100.0, 45, best_long=100, target=112)
    assert isinstance(none, R.NoAlternative) and none.reason == "too_far" and none.cheapest == 55.0    # 110/115; 115 alone is past 10%
    tight = [{"strike": 100, "mid": 4.2}, {"strike": 105, "mid": 3.9}]
    lottery = R.alternative("bullish", tight, 100.0, 40, best_long=100, target=None)    # only a $30 spread fits: refused
    assert isinstance(lottery, R.NoAlternative) and lottery.reason == "too_cheap"


def test_bearish_puts_mirror_and_the_reach_is_three_strikes_from_the_money():
    a = R.alternative("bearish", PUTS, 100.0, 250, best_long=100, target=90)
    assert isinstance(a, R.Alternative) and a.structure == "spread" and a.long_strike == 100 and a.short_strike > 90 and a.cost <= 250
    assert (a.short_strike, a.cost) == (95, 210.0)
    assert R.steps_from_money("bearish", PUTS, 100.0, 85) == 3 and R.steps_from_money("bullish", CALLS, 100.0, 120) == 4
    far = R.alternative("bullish", [{"strike": 100, "mid": 9.0}, {"strike": 125, "mid": 1.0}, {"strike": 130, "mid": 0.8}],
                        100.0, 150, best_long=100, target=None)
    assert isinstance(far, R.NoAlternative)                                             # the spread costs $800; past that is out of reach
    none = R.alternative("bullish", [], 100.0, 500, best_long=100, target=None)
    assert none.reason == "no_options"


def test_every_alternative_sentence_states_its_figures():
    assert copy.alt_tradeoff_spread("bullish", "call", 100, None, 790, None) == \
        "The gain stops at $790 for one contract, where the $100 call alone has no cap."
    assert copy.alt_tradeoff_spread("bullish", "call", 100, 115, 790, 1080).endswith("against $1,080 for the $100/$115 spread.")
    assert "finish above $111.00" in copy.alt_tradeoff_long("bullish", "call", 110, 111.0, 100, 104.2)
    assert "within 3 strikes" in copy.alt_none("too_far", "AAPL", 200, R.ALT_MAX_STEPS, R.ALT_MIN_COST, 325.0)
    assert "$50" in copy.alt_none("too_cheap", "AAPL", 40, R.ALT_MAX_STEPS, R.ALT_MIN_COST, None)
    assert copy.alt_reasoning_spread("call", 300, 420, 100, 4.2, 105, 2.1, 210).startswith("Your budget of $300 is below the $420 the draft costs.")
    assert "No spread from the draft's $100 call fits, so this one starts further out." in \
        copy.alt_reasoning_spread("call", 120, 420, 105, 2.1, 110, 0.95, 115, best_long=100)
    assert "$0.95 a share, $95 for one contract" in copy.alt_reasoning_long("call", 100, 420, 110, 0.95, 95)


def test_no_drafting_route_calls_the_model():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    assert "generate_thesis_draft" not in src                      # neither the draft nor its budget alternative
