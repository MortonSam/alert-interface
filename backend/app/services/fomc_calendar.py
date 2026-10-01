"""FOMC decision days, as data: the one source every FOMC row comes from.

The Federal Reserve's calendar (https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) lists each
scheduled meeting as a two-day range; the decision day is the second day, when the statement is released at
14:00 ET. DECISION_DAYS holds those days for 2021 through 2027, copied from that page on 2026-10-01.

ensure_fomc_events() is the only writer of "FOMC Meeting" event rows. The reactions seeder reads official days
only, so a stray event row is never measured. parse_fed_calendar() reads the Fed page the same way the nightly
validate check does: a month cell of "Apr/May" with a date cell of "30-1" is May 1; a row with a parenthetical
("22 (notation vote)") is not a scheduled meeting and is skipped.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select

FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_EVENT_TITLE = "FOMC Meeting"
MEETING_GAP_DAYS = 7          # two scheduled meetings are never this close: a second event within it is a duplicate
PAGE_HORIZON_DAYS = 365       # the validate check compares every past day and the next 12 months

DECISION_DAYS: dict[int, list[date]] = {
    2021: [date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28), date(2021, 6, 16), date(2021, 7, 28), date(2021, 9, 22), date(2021, 11, 3), date(2021, 12, 15)],
    2022: [date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15), date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14)],
    2023: [date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14), date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13)],
    2024: [date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12), date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18)],
    2025: [date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10)],
    2026: [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)],
    2027: [date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28), date(2027, 6, 9), date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8)],
}

_ALL: frozenset[date] = frozenset(d for days in DECISION_DAYS.values() for d in days)


def decision_days(start: date | None = None, end: date | None = None) -> list[date]:
    """Official decision days in [start, end], ascending."""
    return sorted(d for d in _ALL if (start is None or d >= start) and (end is None or d <= end))


def is_decision_day(d: date) -> bool:
    return d in _ALL


def years_covered() -> list[int]:
    return sorted(DECISION_DAYS)


# ── The Fed page ─────────────────────────────────────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})


def parse_fed_calendar(html: str) -> dict[int, list[date]]:
    """{year: [decision days]} from the Fed's calendar page: the last day of each scheduled meeting range.

    "January" / "27-28" is Jan 28. "Apr/May" / "30-1" is May 1 (the second month, the last day). A single day with a
    note, "22 (notation vote)", is not a scheduled meeting and is skipped; a plain single day is a one-day meeting.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: dict[int, list[date]] = {}
    for panel in soup.find_all("div", class_="panel-default"):
        heading = panel.find("h4")
        m = re.search(r"(\d{4})\s+FOMC", heading.get_text()) if heading else None
        if not m:
            continue
        year = int(m.group(1))
        for row in panel.find_all("div", class_="fomc-meeting"):
            month_div = row.find("div", class_="fomc-meeting__month")
            date_div = row.find("div", class_="fomc-meeting__date")
            if not month_div or not date_div:
                continue
            months = [_MONTHS.get(p.strip().lower()) for p in month_div.get_text(strip=True).split("/")]
            raw = date_div.get_text(strip=True).rstrip("*").strip()
            if "(" in raw or not months or months[-1] is None:
                continue
            try:
                day = int(raw.split("-")[-1].strip())
                out.setdefault(year, []).append(date(year, months[-1], day))
            except ValueError:
                continue
    return {y: sorted(ds) for y, ds in out.items()}


def disagreements(page: dict[int, list[date]], today: date, horizon_days: int = PAGE_HORIZON_DAYS) -> list[str]:
    """Where the page and DECISION_DAYS differ, for every day up to today + horizon, over the years the page shows."""
    end = today + timedelta(days=horizon_days)
    out: list[str] = []
    for year in sorted(set(page) & set(DECISION_DAYS)):
        ours = {d for d in DECISION_DAYS[year] if d <= end}
        theirs = {d for d in page[year] if d <= end}
        for d in sorted(theirs - ours):
            out.append(f"{d.isoformat()}: on the Fed page, not in fomc_calendar.py")
        for d in sorted(ours - theirs):
            out.append(f"{d.isoformat()}: in fomc_calendar.py, not on the Fed page")
    for year in sorted(set(page) - set(DECISION_DAYS)):
        if any(d <= end for d in page[year]):
            out.append(f"{year}: on the Fed page, no dates in fomc_calendar.py")
    return out


def next_year_covered(today: date) -> bool:
    return (today.year + 1) in DECISION_DAYS and bool(DECISION_DAYS[today.year + 1])


# ── The one writer of FOMC event rows ────────────────────────────────────────

async def ensure_fomc_events(session, start: date | None = None, end: date | None = None) -> int:
    """Insert a "FOMC Meeting" event (type macro, source fred) for every official decision day in [start, end]
    that has none. Returns the number inserted. Nothing else writes these rows."""
    from app.models.enums import DataSource, EventType
    from app.models.event import Event

    inserted = 0
    for d in decision_days(start, end):
        existing = await session.scalar(select(Event.id).where(
            Event.ticker_id.is_(None), Event.event_type == EventType.MACRO, Event.title == FOMC_EVENT_TITLE, Event.event_date == d))
        if existing is not None:
            continue
        session.add(Event(ticker_id=None, event_type=EventType.MACRO, event_date=d, title=FOMC_EVENT_TITLE,
                          source=DataSource.FRED, is_confirmed=True, metadata_={}))
        inserted += 1
    return inserted
