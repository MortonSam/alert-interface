"""An expected report window from the company's own past report dates in SEC filings.

For a name no company announcement has confirmed, the window is the only date a page may show once LICENSED_DATES_ONLY is on
(vendor calendars are personal-use only). The past report dates are the filing dates of the company's 8-K Item 2.02 filings whose
documents state per-share results (services/earnings_release.is_earnings_release: Tesla's deliveries release is filed under the
same item and does not count). The next report is projected a year forward from the report one year before it: the centre is that
filing date plus 364 days (the same weekday), and the window is the centre shifted by the smallest and largest of the last
WINDOW_REPORTS year-over-year shifts (each past report against its own year-earlier report). A company with fewer than MIN_PAIRS
such pairs gets no window. WINDOW_VERSION marks the computation; any change to it bumps the version.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

WINDOW_VERSION = 1
WINDOW_REPORTS = 8            # the last eight reports' year-over-year shifts set the window
MIN_PAIRS = 3                 # fewer year-over-year pairs than this: no window
YEAR_DAYS = 364               # a year forward on the same weekday
PAIR_TOLERANCE_DAYS = 45      # a report's year-earlier counterpart lies this close to one year before it
HISTORY_DAYS = 3 * 366        # filings read back this far
SOURCE = "past report dates in SEC filings (8-K Item 2.02)"
KEY = "expected_report_window:{sym}"


@dataclass(frozen=True)
class Window:
    symbol: str
    center: date
    start: date
    end: date
    based_on: list[str]        # the filing dates the projection used, newest first
    pairs: int                 # year-over-year pairs behind the spread
    source: str
    computed_at: str
    computation_version: int

    def as_record(self) -> dict:
        d = asdict(self)
        for k in ("center", "start", "end"):
            d[k] = getattr(self, k).isoformat()
        return d


def release_filing_dates(records: list[dict], today: date) -> list[dict]:
    """Pure: the 8-K Item 2.02 filings of the last HISTORY_DAYS, newest first, as {filing_date, accession} (not yet judged)."""
    since = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    out, seen = [], set()
    for r in sorted(records, key=lambda r: r.get("filing_date", ""), reverse=True):
        items = [i.strip() for i in (r.get("items") or "").split(",")]
        if "2.02" not in items or r.get("filing_date", "") < since or r["filing_date"] in seen:
            continue
        seen.add(r["filing_date"])
        out.append({"filing_date": r["filing_date"], "accession": r.get("accession", "")})
    return out


def yoy_pairs(report_dates: list[date]) -> list[tuple[date, date]]:
    """Pure: (report, its report one year earlier) for every report with a counterpart within PAIR_TOLERANCE_DAYS of a year before."""
    ds = sorted(set(report_dates), reverse=True)
    pairs = []
    for d in ds:
        target = d - timedelta(days=YEAR_DAYS)
        earlier = [e for e in ds if abs((e - target).days) <= PAIR_TOLERANCE_DAYS]
        if earlier:
            pairs.append((d, min(earlier, key=lambda e: abs((e - target).days))))
    return pairs


def expected_window(symbol: str, report_dates: list[date], today: date, now: datetime | None = None) -> Window | None:
    """Pure: the next report's window, or None without enough history. The next report is the one after the newest stored
    report: its year-earlier counterpart is the report nearest one year before today's next due date, projected YEAR_DAYS forward."""
    ds = sorted(set(d for d in report_dates if d <= today), reverse=True)
    pairs = yoy_pairs(ds)[:WINDOW_REPORTS]
    if len(pairs) < MIN_PAIRS or not ds:
        return None
    shifts = [(d - e).days - YEAR_DAYS for d, e in pairs]
    newest = ds[0]
    # the next report follows the newest by about a quarter; its year-earlier counterpart is the report nearest newest + 91 - 364 days
    target = newest + timedelta(days=91) - timedelta(days=YEAR_DAYS)
    counterpart = min(ds, key=lambda e: abs((e - target).days))
    if abs((counterpart - target).days) > PAIR_TOLERANCE_DAYS:
        return None
    center = counterpart + timedelta(days=YEAR_DAYS)
    while center <= today:                       # the projected report already passed with no filing: roll to the following quarter
        counterpart = min(ds, key=lambda e: abs((e - (counterpart + timedelta(days=91))).days))
        nxt = counterpart + timedelta(days=YEAR_DAYS)
        if nxt <= center:
            return None
        center = nxt
    return Window(symbol, center, center + timedelta(days=min(shifts)), center + timedelta(days=max(shifts)),
                  [d.isoformat() for d in ds[:WINDOW_REPORTS + 4]], len(pairs), SOURCE,
                  (now or datetime.now()).isoformat(), WINDOW_VERSION)


def window_from_record(raw: str | None) -> dict | None:
    """The stored window as a dict with dates, or None when absent or from another version."""
    import json
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    if d.get("computation_version") != WINDOW_VERSION:
        return None
    return d
