"""The expected move is paused when the ATM straddle's combined bid-ask spread is above MAX_STRADDLE_SPREAD_PCT of its mid
(services/implied_move), with one plain note for visitors."""
from pathlib import Path

from app.services import implied_move as M


def leg(k, bid, ask, last=None):
    return {"strike": k, "bid": bid, "ask": ask, "lastPrice": last}


def test_the_spread_is_both_legs_together_against_both_mids():
    assert M.straddle_spread_pct(leg(15, 0.02, 0.03), leg(15, 0.05, 0.25)) == (0.01 + 0.20) / (0.025 + 0.15) * 100   # AES, Oct 8: 120%
    assert M.straddle_spread_pct(leg(15, None, 0.03), leg(15, 0.05, 0.25)) is None                                  # one-sided: unknown
    assert M.straddle_spread_pct(leg(15, 0.0, 0.10), leg(15, 0.0, 0.10)) == 200.0


def test_above_the_limit_the_move_is_withheld_and_the_reason_is_known():
    calls, puts = [leg(15, 0.02, 0.03), leg(16, 0.01, 0.02)], [leg(15, 0.05, 0.25), leg(16, 0.6, 1.4)]
    assert M.straddle_implied_move(calls, puts, 14.93) is None
    assert M.wide_quotes(calls, puts, 14.93)
    assert M.straddle_implied_move(calls, puts, 14.93, gate=False) is not None          # the vendor comparison still measures it


def test_at_or_below_the_limit_the_move_shows():
    calls, puts = [leg(100, 1.0, 3.0)], [leg(100, 1.0, 3.0)]                               # 4 of 4: exactly 100%
    assert M.straddle_spread_pct(calls[0], puts[0]) == 100.0
    assert M.straddle_implied_move(calls, puts, 100.0).pct == 0.04
    assert not M.wide_quotes(calls, puts, 100.0)


def test_the_visitor_note_is_exact_and_names_no_vendor_or_number():
    assert M.WIDE_QUOTES_NOTE == ("The expected move for this stock is paused until the next update. "
                                  "Its options quotes are too wide right now to give a reliable number.")
    low = M.WIDE_QUOTES_NOTE.lower()
    assert not any(w in low for w in ("intrinio", "courier", "finnhub", "%", "spread", "bid", "ask", "100"))
    assert M.MAX_STRADDLE_SPREAD_PCT == 100.0


def test_every_page_move_reads_the_gate():
    src = (Path(__file__).parents[1] / "app" / "routers" / "tickers.py").read_text()
    assert src.count("data_quality_note = WIDE_QUOTES_NOTE") == 2                        # /expected-move and the options bundle
    assert src.count("not too_wide(") == 2                                                 # the watchlist row and Ivy's Read
