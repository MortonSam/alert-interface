"""Unit tests for exit_date calculation (trading day arithmetic)."""
from datetime import date

from app.services.trading_calendar import nth_trading_day_after


def test_basic_weekday():
    """Monday event -> 5 trading days later is the following Monday."""
    # 2026-09-14 is a Monday
    assert nth_trading_day_after(date(2026, 9, 14), 5) == date(2026, 9, 21)


def test_across_weekend():
    """Wednesday event -> 5 trading days spans into the next week."""
    # 2026-09-16 is a Wednesday, +5 trading days = Wed Sep 23
    assert nth_trading_day_after(date(2026, 9, 16), 5) == date(2026, 9, 23)


def test_friday_event():
    """Friday event -> 5 trading days later is the following Friday."""
    # 2026-09-18 is a Friday, +5 trading days = Fri Sep 25
    assert nth_trading_day_after(date(2026, 9, 18), 5) == date(2026, 9, 25)


def test_across_labor_day():
    """Labor Day (first Monday of September) is skipped.

    2026 Labor Day = Sep 7 (Monday).
    Event on Wed Sep 2: +5 trading days should skip Labor Day.
    Sep 2 (Wed) -> Sep 3 (Thu) -> Sep 4 (Fri) -> Sep 8 (Tue, skip wknd+LD)
    -> Sep 9 (Wed) -> Sep 10 (Thu)
    """
    assert nth_trading_day_after(date(2026, 9, 2), 5) == date(2026, 9, 10)


def test_across_thanksgiving():
    """Thanksgiving (4th Thursday of November) is skipped.

    2026 Thanksgiving = Nov 26.
    Event on Mon Nov 23: +5 trading days should skip Thanksgiving.
    Nov 23 (Mon) -> Nov 24 (Tue) -> Nov 25 (Wed) -> Nov 27 (Fri, skip Thu)
    -> Nov 30 (Mon) -> Dec 1 (Tue)
    """
    assert nth_trading_day_after(date(2026, 11, 23), 5) == date(2026, 12, 1)


def test_across_christmas():
    """Christmas Day observed is skipped.

    2026-12-25 is a Friday, so observed on Friday.
    Event on Mon Dec 21: +5 trading days should skip Christmas.
    Dec 21 (Mon) -> Dec 22 (Tue) -> Dec 23 (Wed) -> Dec 24 (Thu)
    -> Dec 26 (skip Dec 25 Christmas, skip wknd) -> Dec 28 (Mon)
    Wait, Dec 26 is Saturday. So:
    Dec 21 (Mon) -> Dec 22 (Tue) -> Dec 23 (Wed) -> Dec 24 (Thu)
    -> skip Dec 25 (Christmas/Fri) -> Dec 28 (Mon) = 5th trading day
    """
    assert nth_trading_day_after(date(2026, 12, 21), 5) == date(2026, 12, 29)


def test_across_good_friday():
    """Good Friday is a NYSE holiday (not a federal holiday).

    2027 Good Friday = March 26.
    Event on Mon March 22: +5 trading days should skip Good Friday.
    Mar 22 (Mon) -> +1 Mar 23 (Tue) -> +2 Mar 24 (Wed) -> +3 Mar 25 (Thu)
    -> skip Mar 26 (Good Friday) + weekend -> +4 Mar 29 (Mon) -> +5 Mar 30 (Tue)
    """
    assert nth_trading_day_after(date(2027, 3, 22), 5) == date(2027, 3, 30)


def test_zero_offset():
    """Zero offset returns the same date if it is a trading day."""
    # 2026-09-14 is a Monday (trading day)
    assert nth_trading_day_after(date(2026, 9, 14), 0) == date(2026, 9, 14)


def test_one_offset():
    """One trading day after a Friday is the next Monday."""
    # 2026-09-18 is a Friday
    assert nth_trading_day_after(date(2026, 9, 18), 1) == date(2026, 9, 21)
