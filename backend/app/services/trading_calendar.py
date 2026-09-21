"""NYSE trading-day arithmetic.

Uses pandas CustomBusinessDay with an NYSE holiday calendar so that
prospective exit_date calculations match the row-based offsets in
seed_historical_reactions (which counts actual trading rows in yfinance
OHLCV data).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)
from pandas.tseries.offsets import CustomBusinessDay


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """Holidays when the NYSE is closed."""
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-06-20",
                observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_NYSE_BDAY = CustomBusinessDay(calendar=NYSEHolidayCalendar())


def nth_trading_day_after(event_date: date, n: int = 5) -> date:
    """Return the nth NYSE trading day after *event_date*.

    Day 0 is event_date itself (if it is a trading day).
    Day 1 is the next trading day, etc.
    """
    ts = pd.Timestamp(event_date) + n * _NYSE_BDAY
    return ts.date()


def sessions_after(last: date, ref: date) -> int:
    """NYSE sessions strictly after `last` and strictly before `ref`.

    Counts completed sessions a price series is missing: `ref` itself is
    excluded because today's bar may not exist yet.
    """
    if ref <= last:
        return 0
    days = pd.date_range(pd.Timestamp(last) + _NYSE_BDAY, pd.Timestamp(ref) - pd.Timedelta(days=1), freq=_NYSE_BDAY)
    return len(days)
