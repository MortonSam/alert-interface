"""The ticker header's day high and low come from the session's own bars (services/session_range), never the quote vendor's h/l."""
from datetime import date, datetime

import pytest

from app.services import session_range as SR
from app.services.live_data import NY


def test_session_of_reads_the_new_york_date():
    assert SR.session_of(int(datetime(2026, 10, 15, 16, 0, tzinfo=NY).timestamp())) == date(2026, 10, 15)
    assert SR.session_of(int(datetime(2026, 10, 15, 23, 30, tzinfo=NY).timestamp())) == date(2026, 10, 15)
    assert SR.session_of(None) is None


def test_range_from_bars_takes_the_extremes_and_skips_empty_bars():
    assert SR.range_from_bars([363.7, None, 360.1], [355.24, 358.0, None]) == (363.7, 355.24)
    assert SR.range_from_bars([], [1.0]) is None
    assert SR.range_from_bars([0, None], [0]) is None
    assert SR.range_from_bars([10.0], [11.0]) is None          # a high under the low is not a range


def test_a_range_that_misses_the_price_is_not_shown():
    assert SR.holds_price(363.7, 355.24, 362.44)
    assert not SR.holds_price(355.0, 350.0, 362.44)            # the TSLA case: a "high" below the last trade
    assert SR.holds_price(363.7, 355.24, None)


@pytest.mark.asyncio
async def test_stored_bar_wins_then_intraday_then_nothing(monkeypatch):
    ts = int(datetime(2026, 10, 14, 16, 0, tzinfo=NY).timestamp())
    monkeypatch.setattr(SR, "_stored_bar", lambda s, d: (371.39, 363.82))
    got = await SR.session_range("TSLA", ts, 367.16)
    assert (got.high, got.low, got.source, got.session) == (371.39, 363.82, "daily bar", date(2026, 10, 14))

    monkeypatch.setattr(SR, "_stored_bar", lambda s, d: None)

    async def chart(symbol, on, prev_close, *a, **k):
        assert on == date(2026, 10, 14)
        return {"highs": [371.32, 368.0], "lows": [365.0, 363.84]}
    import app.services.live_data as L
    monkeypatch.setattr(L, "intraday_chart", chart)
    got = await SR.session_range("TSLA", ts, 367.16)
    assert (got.high, got.low, got.source) == (371.32, 363.84, "intraday bars")

    async def failing(*a, **k):
        raise RuntimeError("vendor down")
    monkeypatch.setattr(L, "intraday_chart", failing)
    assert await SR.session_range("TSLA", ts, 367.16) is None
    assert await SR.session_range("TSLA", None, 367.16) is None
