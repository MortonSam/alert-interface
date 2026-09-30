"""The implied move is one computation for every page, labelled with the window it covers.

Audit item 7: the ticker page compared an implied move priced to a multi-week expiry with one-day earnings
history and counted history "above/below" it; Build computed the straddle in its own loop. Now
services/implied_move.straddle_implied_move is the one computation (same expiry and spot: same number
everywhere), the response names the span from the chain's date to the expiry, and the above/below count
is gone. Audit item 4: the fact block tells the chain's spot from the live quote.
"""
import re
from pathlib import Path

from app.schemas.options import ExpectedMoveRead, HistoricalMoveStats
from app.services.implied_move import mid_or_last, span_days, straddle_implied_move

CALLS = [{"strike": 330.0, "bid": 12.0, "ask": 12.4, "lastPrice": 12.1}, {"strike": 340.0, "bid": 7.0, "ask": 7.2, "lastPrice": 7.1},
         {"strike": 350.0, "bid": 3.5, "ask": 3.7, "lastPrice": 3.6}]
PUTS = [{"strike": 330.0, "bid": 4.0, "ask": 4.2, "lastPrice": 4.1}, {"strike": 340.0, "bid": 8.8, "ask": 9.0, "lastPrice": 8.9},
        {"strike": 350.0, "bid": 15.0, "ask": 15.4, "lastPrice": 15.2}]


def test_the_same_chain_and_spot_give_the_same_move_whoever_asks():
    a = straddle_implied_move(CALLS, PUTS, 339.85)
    b = straddle_implied_move(list(reversed(CALLS)), list(reversed(PUTS)), 339.85)
    assert a == b and a is not None
    assert a.atm_strike == 340.0 and a.straddle == 7.1 + 8.9
    assert round(a.pct, 4) == round(16.0 / 339.85, 4) and (a.low, a.high) == (339.85 - 16.0, 339.85 + 16.0)
    # a different spot is a different number: the pages agree only when they pass the same spot
    assert straddle_implied_move(CALLS, PUTS, 332.35).pct != a.pct
    assert straddle_implied_move(CALLS, PUTS, None) is None and straddle_implied_move([], PUTS, 339.85) is None
    assert straddle_implied_move([{"strike": 340.0, "bid": 0, "ask": 0, "lastPrice": 0}], PUTS, 339.85) is None   # no priced ATM pair
    assert mid_or_last(1.0, 1.2, 5.0) == 1.1 and mid_or_last(0, 1.2, 0.9) == 0.9 and mid_or_last(0, 0, 0) is None


def test_the_span_is_named_from_the_chain_date_to_the_expiry_never_from_the_request():
    assert span_days("2026-09-28", "2026-11-20") == 53
    assert span_days("2026-09-28T20:00:00+00:00", "2026-11-20") == 53
    assert span_days(None, "2026-11-20") is None and span_days("2026-09-28", None) is None and span_days("bad", "2026-11-20") is None
    assert "chain_date" in ExpectedMoveRead.model_fields and "span_days" in ExpectedMoveRead.model_fields
    assert not {"above_expected", "below_expected"} & set(HistoricalMoveStats.model_fields)


def test_every_page_takes_the_move_from_the_one_service_and_build_tells_the_two_prices_apart():
    root = Path(__file__).resolve().parents[1] / "app"
    tickers = (root / "routers" / "tickers.py").read_text()
    thesis = (root / "routers" / "thesis.py").read_text()
    for src, name in ((tickers, "tickers"), (thesis, "thesis")):
        assert "straddle_implied_move(" in src, name
        assert "straddle_price = call_price + put_price" not in src and "straddle = cp + pp" not in src, name
        assert "above_expected" not in src, name
    assert tickers.count("straddle_implied_move(") == 2      # /expected-move and the bundle
    assert re.search(r'"quote_price":\s+round\(data\["current_price"\], 2\)', thesis)
    assert re.search(r'"span_days":\s+span_days\(options_as_of, chosen_exp\)', thesis)
    assert "chain_date=str(chain_last_trade)[:10]" in tickers and tickers.count("span_days=span_days(chain_last_trade, chosen_exp)") == 2
