"""is_trading_day reads each year's holidays once (Discover's rank-hold cutoff asks for a year of days per request) and
agrees with the calendar's own rule day by day."""
import time
from datetime import date, timedelta

import pandas as pd

from app.services import trading_calendar as T
from app.services.rv_hold import sessions_cutoff


def _rule(d: date) -> bool:
    if d.weekday() >= 5 or d in T.SPECIAL_CLOSURES:
        return False
    return len(T.NYSEHolidayCalendar().holidays(pd.Timestamp(d), pd.Timestamp(d))) == 0


def test_the_cached_years_agree_with_the_rule_on_every_day_of_2025_and_2026():
    d = date(2025, 1, 1)
    while d <= date(2026, 12, 31):
        assert T.is_trading_day(d) == _rule(d), d
        d += timedelta(days=1)
    assert not T.is_trading_day(date(2025, 1, 9)) and T.is_trading_day(date(2021, 12, 31))


def test_a_year_of_sessions_is_fast():
    t = time.perf_counter()
    sessions_cutoff(date(2026, 10, 9))
    assert time.perf_counter() - t < 0.05
