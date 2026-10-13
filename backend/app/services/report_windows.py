"""An expected report window from the company's own past report dates in SEC filings.

For a name no company announcement has confirmed, the window is the only date a page may show once LICENSED_DATES_ONLY is on
(vendor calendars are personal-use only). The past report dates are the filing dates of the company's 8-K Item 2.02 filings of
the last three years, read from its SEC submissions index (one request, older pages only until three years are covered). Item
2.02 marks earnings, so a company filing four a year is taken at its word without reading a document. A company with more than
SPAN_REPORTS filings inside any SPAN_DAYS (Tesla's deliveries releases go under the same item; ABBV's in-process R&D updates) has
each filing's documents read for per-share results (services/earnings_release.is_earnings_release), and only those count. Each filing's verdict is stored per
company (VERDICTS_KEY), so a night reads only filings it has not judged. The next report is projected a year forward from the report one year before it: the centre is that
filing date plus 364 days (the same weekday), and the window is the centre shifted by the smallest and largest of the last
WINDOW_REPORTS year-over-year shifts (each past report against its own year-earlier report), its start a further FILING_LAG_DAYS
earlier (a release after the close is often filed the next morning, so the filing date can trail the report by a day). The next
report is projected from the earliest past report whose year-later successor has not been filed, so a window stays until its end
passes and a guidance update filed weeks before a report never stands in for it. A company with fewer than MIN_PAIRS
such pairs gets no window. WINDOW_VERSION marks the computation; any change to it bumps the version.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

WINDOW_VERSION = 2            # 2: report dates from the submissions index, documents read only for ambiguous companies (1 read every filing)
WINDOW_REPORTS = 8            # the last eight reports' year-over-year shifts set the window
MIN_PAIRS = 3                 # fewer year-over-year pairs than this: no window
YEAR_DAYS = 364               # a year forward on the same weekday
PAIR_TOLERANCE_DAYS = 45      # a report's year-earlier counterpart lies this close to one year before it
HISTORY_DAYS = 3 * 366        # filings read back this far
SOURCE = "past report dates in SEC filings (8-K Item 2.02)"
KEY = "expected_report_window:{sym}"
VERDICTS_KEY = "release_filing_verdicts:{sym}"   # {accession: {"filed", "earnings", "basis": "item" | "document"}}
SPAN_REPORTS, SPAN_DAYS = 4, 350   # more Item 2.02 filings than four inside any 350 days (five quarterly reports span about 364): documents decide
REGULAR_SHIFT_DAYS = 14      # a pair further than this from a year apart is a stray filing against a report, never part of the cadence
OPEN_AFTER_CENTRE_DAYS = 7   # a projection with no filing stays the next report at most a week past its centre (BLK 2026: centre Oct 9, report Oct 14)
FILING_LAG_DAYS = 1           # the window opens a day earlier: the 8-K of an after-close release is often filed the next morning


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


def years_covered(reach: str | None, today: date) -> float:
    """Pure: the years of filing history the index pages read reach back, at most HISTORY_DAYS and at least a quarter."""
    if not reach:
        return 0.25
    days = (today - date.fromisoformat(reach)).days
    return max(0.25, min(days, HISTORY_DAYS) / 365.25)


def is_ambiguous(filings: list[dict], reach: str | None = None, today: date | None = None) -> bool:
    """Pure: more than SPAN_REPORTS Item 2.02 filings inside some SPAN_DAYS, so the item alone does not mark earnings. Judged
    span by span, not on average: one stray filing in one year (ABBV, REGN, EMR in 2026) is enough."""
    ds = sorted(date.fromisoformat(f["filing_date"]) for f in filings)
    return any(len([d for d in ds[i:] if (d - first).days < SPAN_DAYS]) > SPAN_REPORTS for i, first in enumerate(ds))


def to_read(filings: list[dict], stored: dict, ambiguous: bool) -> list[dict]:
    """Pure: the filings whose documents must be read tonight: none for a company taken at the item's word, and for an
    ambiguous one only those without a stored document verdict."""
    if not ambiguous:
        return []
    return [f for f in filings if (stored.get(f["accession"]) or {}).get("basis") != "document"]


def verdicts(filings: list[dict], stored: dict, ambiguous: bool, read: dict[str, bool]) -> dict:
    """Pure: every filing's verdict, as stored: the item's word for a company that is not ambiguous, else the document read
    (tonight's, or the stored one). A filing an ambiguous company's read failed tonight is left out, to be read the next night."""
    out = {}
    for f in filings:
        acc = f["accession"]
        if not ambiguous:
            out[acc] = {"filed": f["filing_date"], "earnings": True, "basis": "item"}
        elif acc in read:
            out[acc] = {"filed": f["filing_date"], "earnings": read[acc], "basis": "document"}
        elif (stored.get(acc) or {}).get("basis") == "document":
            out[acc] = stored[acc]
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
    """Pure: the next report's window, or None without enough history. Every past report whose year-later successor has not been
    filed yet projects YEAR_DAYS forward; the next report is the earliest projection whose window has not closed. A report has
    its successor when a later filing takes it as its year-earlier counterpart, so a company that files a guidance update weeks
    before each report (ABBV, REGN) still projects from the report itself, never from the newest filing."""
    ds = sorted(set(d for d in report_dates if d <= today), reverse=True)
    regular = [(d, e) for d, e in yoy_pairs(ds) if abs((d - e).days - YEAR_DAYS) <= REGULAR_SHIFT_DAYS]
    pairs = regular[:WINDOW_REPORTS]
    if len(pairs) < MIN_PAIRS or not ds:
        return None
    shifts = [(d - e).days - YEAR_DAYS for d, e in pairs]
    succeeded = {e for _, e in yoy_pairs(ds)}
    on_cadence = {d for d, _ in regular}                       # only a report with a regular year-earlier pair projects the next one
    ds = [e for e in ds if e in on_cadence]
    grace = min(max(shifts), OPEN_AFTER_CENTRE_DAYS)          # a stray filing a year ago never holds a window open for weeks
    open_ = sorted(e + timedelta(days=YEAR_DAYS) for e in ds if e not in succeeded and e + timedelta(days=YEAR_DAYS + grace) >= today)
    if not open_:
        return None
    center = open_[0]
    return Window(symbol, center, center + timedelta(days=min(shifts) - FILING_LAG_DAYS), center + timedelta(days=max(shifts)),
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
