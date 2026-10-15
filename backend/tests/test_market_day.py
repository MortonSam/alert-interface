"""Moves beside the market (services/market_day): SPY's move on a session from its stored closes, and the with-the-market rule."""
from datetime import date

import pytest
from sqlalchemy import text

from app.routers.discover import UnusuallyActiveItem, shared_dominant_session
from app.services.market_day import spy_moves, with_market
from app.thresholds import MARKET_DAY_MIN_SHARE, MARKET_DAY_MIN_SPY_PCT


def test_with_market_needs_a_real_spy_move_and_most_stocks_the_same_way():
    assert MARKET_DAY_MIN_SPY_PCT == 1.0 and MARKET_DAY_MIN_SHARE == 0.7
    got = with_market([-9.8, -4.1, -3.0, -2.2, 1.5], -2.1)
    assert got == {"spy_move_pct": -2.1, "same_way": 4, "total": 5, "direction": "down"}
    assert with_market([-9.8, -4.1, -3.0, -2.2, 1.5], -0.4) is None            # a quiet market: the moves are the stocks' own
    assert with_market([-9.8, 4.1, 3.0, -2.2, 1.5], -2.1) is None               # 2 of 5 with SPY is not most
    assert with_market([-9.8, -4.1], None) is None                              # no SPY figure, no claim
    assert with_market([], 2.0) is None


def test_a_shared_session_says_whether_it_moved_with_the_market():
    rows = [UnusuallyActiveItem(symbol=s, name=s, rv_rank=90.0, rv_20d=0.3, tier="extreme", dominant_date="2026-10-09", dominant_move_pct=m, spy_move_pct=-1.6)
            for s, m in (("T", -10.8), ("TMUS", -6.0), ("CCI", -4.0))]
    got = shared_dominant_session(rows)
    assert got["with_market"] is True and got["spy_move_pct"] == -1.6
    quiet = [r.model_copy(update={"spy_move_pct": -0.3}) for r in rows]
    assert shared_dominant_session(quiet)["with_market"] is False


@pytest.mark.asyncio
async def test_spy_moves_reads_the_stored_closes_as_traded():
    from app.database import ScriptSessionLocal
    async with ScriptSessionLocal() as s:
        await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, fetched_at)
            VALUES ('SPY', '2031-01-02', 'test', 100, 101, 99, 100, 1, now()), ('SPY', '2031-01-03', 'test', 98, 99, 97, 98, 1, now())"""))
        try:
            got = await spy_moves(s, {date(2031, 1, 3), date(2031, 1, 6)})
        finally:
            await s.rollback()
    assert got == {"2031-01-03": -2.0}                                          # Jan 6 has no stored close: absent, never estimated


def test_usual_daily_move_is_the_median_absolute_close_to_close_move():
    from app.routers.historical_reactions import USUAL_MOVE_MIN_SESSIONS, median_abs_daily_move
    closes = [100.0]
    for i in range(USUAL_MOVE_MIN_SESSIONS):
        closes.append(closes[-1] * (1.01 if i % 2 else 0.98))                  # alternating +1% and -2%
    got, n = median_abs_daily_move(closes)
    assert n == USUAL_MOVE_MIN_SESSIONS and got == 1.5                           # median of 30 x 1% and 30 x 2%
    assert median_abs_daily_move(closes[:10]) == (None, 9)                        # too few sessions: no usual move, no claim
