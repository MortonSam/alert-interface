"""Earnings markers on the price chart for reports whose reaction has not settled yet (Sam, 2026-10-19). A confirmed report shows
its marker as soon as its date passes; the reaction row (and with it the EPS outcome and the moves) fills in when the seeder's
window settles. JPM's Oct 13, 2026 report had no marker while its window was open."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SAME_REPORT_DAYS = 1      # a reaction row within a day of the event is the same report (an after-close report's row can sit a day apart)


def today_ny() -> date:
    return datetime.now(NY).date()


def settling_dates(reaction_dates: list[date], event_dates: list[date], min_date: date, today: date) -> list[date]:
    """Pure: the confirmed past report dates in the chart's window that have no reaction row yet, oldest first."""
    return sorted({d for d in event_dates
                   if min_date <= d <= today and not any(abs((d - r).days) <= SAME_REPORT_DAYS for r in reaction_dates)})
