"""The 1-day chart at the open (Sam, 2026-10-27): until today's delayed bars cover MIN_TODAY_BAR_MINUTES, the chart shows the last full
session, labeled with its date (live_data.one_day_session)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.live_data import CHART_BAR_MINUTES, MIN_TODAY_BAR_MINUTES, one_day_session

NY = ZoneInfo("America/New_York")


def bars(day: str, first: str, last: str) -> list[str]:
    t, end = datetime.fromisoformat(f"{day}T{first}:00-04:00"), datetime.fromisoformat(f"{day}T{last}:00-04:00")
    out = []
    while t <= end:
        out.append(t.isoformat())
        t += timedelta(minutes=CHART_BAR_MINUTES)
    return out


def test_at_9_49_the_chart_shows_the_previous_full_session():
    # 15-minute delayed bars: at 9:49 AM ET only the 9:30 bar is in
    now = datetime(2026, 10, 27, 9, 49, tzinfo=NY)
    assert one_day_session(now, bars("2026-10-27", "09:30", "09:30")) == (date(2026, 10, 26), False)
    assert one_day_session(now, []) == (date(2026, 10, 26), False)


def test_at_10_30_the_chart_shows_today():
    # bars from 9:30 through 10:10 (nine five-minute bars, 45 minutes)
    now = datetime(2026, 10, 27, 10, 30, tzinfo=NY)
    assert one_day_session(now, bars("2026-10-27", "09:30", "10:10")) == (date(2026, 10, 27), True)


def test_the_threshold_and_the_days_around_it():
    assert MIN_TODAY_BAR_MINUTES == 30
    now = datetime(2026, 10, 27, 10, 20, tzinfo=NY)
    assert one_day_session(now, bars("2026-10-27", "09:30", "09:50"))[1] is False          # five bars, 25 minutes
    assert one_day_session(now, bars("2026-10-27", "09:30", "09:55"))[1] is True           # six bars, 30 minutes
    assert one_day_session(datetime(2026, 10, 27, 8, 0, tzinfo=NY), []) == (date(2026, 10, 26), False)       # before the open
    assert one_day_session(datetime(2026, 10, 26, 9, 45, tzinfo=NY), bars("2026-10-26", "09:30", "09:30")) == (date(2026, 10, 23), False)   # a Monday: Friday
    assert one_day_session(datetime(2026, 10, 25, 12, 0, tzinfo=NY), []) == (date(2026, 10, 23), False)      # a Sunday
    # yesterday's bars never count as today's
    assert one_day_session(datetime(2026, 10, 27, 9, 49, tzinfo=NY), bars("2026-10-26", "09:30", "16:00")) == (date(2026, 10, 26), False)
