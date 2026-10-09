"""NYSE trading-day arithmetic.

Uses pandas CustomBusinessDay with an NYSE holiday calendar so that
prospective exit_date calculations match the row-based offsets in
seed_historical_reactions (which counts actual trading rows in yfinance
OHLCV data).
"""
from __future__ import annotations

import functools
from datetime import date, timedelta

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
    sunday_to_monday,
)
from pandas.tseries.offsets import CustomBusinessDay


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """Holidays when the NYSE is closed."""
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),   # NYSE: no Friday observance when Jan 1 is a Saturday (2021-12-31 traded)
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


# Closures no rule derives: the exchange announced them. validate's calendar_matches_spy_bars check finds a missing one.
SPECIAL_CLOSURES: dict[date, str] = {
    date(2025, 1, 9): "National Day of Mourning for President Carter",
}

# Days whose session status this calendar once got wrong, with the day the correction landed. A reaction window that
# touches one of these is recomputed once by the nightly recompute (rows written before the correction).
CALENDAR_CORRECTIONS: dict[date, tuple[str, date]] = {
    date(2021, 12, 31): ("was treated as a holiday; the NYSE traded", date(2026, 10, 6)),
    date(2025, 1, 9): ("was treated as a session; the NYSE was closed", date(2026, 10, 6)),
}

_NYSE_BDAY = CustomBusinessDay(calendar=NYSEHolidayCalendar(), holidays=[pd.Timestamp(d) for d in SPECIAL_CLOSURES])


@functools.lru_cache(maxsize=None)
def _holidays_in_year(year: int) -> frozenset[date]:
    """The calendar's holidays in one year, computed once per process (building them costs about 5 ms; Discover's rank-hold
    cutoff asks for a year of days on every request)."""
    days = NYSEHolidayCalendar().holidays(pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31))
    return frozenset(ts.date() for ts in days)


def is_trading_day(d: date) -> bool:
    """A weekday that is not an NYSE holiday or a special closure."""
    if d.weekday() >= 5 or d in SPECIAL_CLOSURES:
        return False
    return d not in _holidays_in_year(d.year)


def is_half_day(d: date) -> bool:
    """An NYSE early close (1 p.m.): the day after Thanksgiving, Christmas Eve on a weekday, and July 3 on a
    weekday when Independence Day is on a weekday too."""
    if not is_trading_day(d):
        return False
    if d.month == 11 and d.weekday() == 4 and 23 <= d.day <= 29 and not is_trading_day(d - timedelta(days=1)):
        return True                       # the Friday after Thanksgiving
    if d.month == 12 and d.day == 24:
        return True
    if d.month == 7 and d.day == 3 and date(d.year, 7, 4).weekday() < 5:
        return True
    return False


def nth_trading_day_after(event_date: date, n: int = 5) -> date:
    """Return the nth NYSE trading day after *event_date*.

    Day 0 is event_date itself (if it is a trading day).
    Day 1 is the next trading day, etc.
    """
    ts = pd.Timestamp(event_date) + n * _NYSE_BDAY
    return ts.date()


def last_session_before(d: date) -> date:
    """The latest NYSE session strictly before `d`."""
    return (pd.Timestamp(d) - _NYSE_BDAY).date()


def sessions_after(last: date, ref: date) -> int:
    """NYSE sessions strictly after `last` and strictly before `ref`.

    Counts completed sessions a price series is missing: `ref` itself is
    excluded because today's bar may not exist yet.
    """
    if ref <= last:
        return 0
    days = pd.date_range(pd.Timestamp(last) + _NYSE_BDAY, pd.Timestamp(ref) - pd.Timedelta(days=1), freq=_NYSE_BDAY)
    return len(days)
