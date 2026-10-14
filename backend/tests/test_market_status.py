"""The market status comes from the NYSE calendar: weekends, holidays, announced closures and 1 p.m. early closes."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.market_status import REASONS, market_session, session_for

NY = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


def test_a_regular_day_opens_at_930_and_closes_at_4():
    s = session_for(date(2026, 10, 14))
    assert (s["is_trading_day"], s["half_day"], s["reason"]) == (True, False, "regular")
    assert s["open_at"] == "2026-10-14T09:30:00-04:00" and s["close_at"] == "2026-10-14T16:00:00-04:00"
    assert market_session(at(2026, 10, 14, 9, 29))["is_open"] is False
    assert market_session(at(2026, 10, 14, 9, 30))["is_open"] is True
    assert market_session(at(2026, 10, 14, 15, 59))["is_open"] is True
    assert market_session(at(2026, 10, 14, 16, 0))["is_open"] is False


def test_holidays_and_weekends_have_no_session_and_name_the_next_one():
    thanksgiving = market_session(at(2026, 11, 26, 11, 0))
    assert thanksgiving["is_open"] is False and thanksgiving["today"]["reason"] == "holiday"
    assert thanksgiving["next"]["date"] == "2026-11-27"
    assert session_for(date(2026, 12, 25))["reason"] == "holiday"
    assert session_for(date(2027, 1, 1))["reason"] == "holiday"
    assert session_for(date(2026, 10, 17))["reason"] == "weekend"
    assert session_for(date(2025, 1, 9))["reason"] == "special_closure"
    assert market_session(at(2026, 10, 16, 17, 0))["next"]["date"] == "2026-10-19"          # Friday evening: Monday
    assert set(REASONS) >= {session_for(d)["reason"] for d in (date(2026, 10, 14), date(2026, 11, 27), date(2026, 10, 17), date(2026, 12, 25), date(2025, 1, 9))}


@pytest.mark.parametrize("day", [date(2026, 11, 27), date(2026, 12, 24)])
def test_half_days_close_at_1(day):
    s = session_for(day)
    assert s["half_day"] is True and s["close_at"].endswith("T13:00:00-05:00")
    assert market_session(datetime.combine(day, datetime.min.time(), NY).replace(hour=12, minute=59))["is_open"] is True
    assert market_session(datetime.combine(day, datetime.min.time(), NY).replace(hour=13, minute=0))["is_open"] is False


def test_july_3_is_a_half_day_only_when_the_fourth_is_a_weekday():
    assert session_for(date(2025, 7, 3))["half_day"] is True       # Friday the 4th
    assert session_for(date(2026, 7, 3))["is_trading_day"] is False   # Saturday the 4th, observed Friday the 3rd


@pytest.mark.asyncio
async def test_the_endpoint_serves_the_session():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/system/market-session")).json()
    assert set(body) == {"as_of", "is_open", "today", "next"} and body["today"]["reason"] in REASONS
