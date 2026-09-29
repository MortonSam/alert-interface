"""Earnings dates with their confirmation level, from every source, decided one way.

A stored earnings date is one of:
  confirmed    the company set it (an announcement the calendar step fetched) or two independent
               sources name the same day; or the report happened (evidence of an actual EPS or an
               8-K Item 2.02), in which case the date is the report date.
  estimated    one source's estimate (Finnhub or Yahoo Finance); the note names the source.
  unresolved   an estimate whose date passed with no report found by any source: kept as
               "expected around <date>; not confirmed", never labelled past.

merge_future() decides the future dates from the sources' candidates; resolve_past() decides what
becomes of an estimate that passed. Both are pure: the script fetches, these functions decide, the
script applies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

NEAR_DAYS = 3                        # candidates this close from different sources are the same report
FAR_AFTER_LAST_REPORT_DAYS = 100     # a next date this long after the last report is not the next quarter
QUARTER_DAYS = 91
SUPERSEDED_DAYS = 21                 # a reaction row this close to a past estimate: the quarter was reported
REPLACED_BY_ESTIMATE_DAYS = 14       # a nearer future estimate this close after a past estimate replaces it
EVIDENCE_DAYS = 3                    # an actual EPS this close to the estimate is that report
EDGAR_202_LOOKBACK_DAYS = 5          # 8-K Item 2.02 filed within this many days of the estimate

SOURCE_LABELS = {"finnhub": "Finnhub", "yfinance": "Yahoo Finance", "company": "company announcement"}


@dataclass(frozen=True)
class Candidate:
    day: date
    source: str          # "finnhub" | "yfinance" | "company"
    timing: str = "unknown"
    evidence: str = ""   # for "company": what was fetched, e.g. "8-K Item 7.01 filed 2026-08-28"


@dataclass
class FutureDate:
    day: date
    confirmed: bool
    note: str            # "confirmed: Finnhub and Yahoo Finance agree" / "estimated (Yahoo Finance); Finnhub says 2026-09-28"
    source: str          # the source whose date was kept
    timing: str = "unknown"


@dataclass
class PastResolution:
    action: str                       # "superseded" | "reported" | "unresolved"
    note: str
    report_date: date | None = None   # for "reported": the evidenced date
    sources_checked: dict = field(default_factory=dict)


def _cluster(cands: list[Candidate]) -> list[list[Candidate]]:
    out: list[list[Candidate]] = []
    for c in sorted(cands, key=lambda c: (c.day, c.source)):
        if out and (c.day - out[-1][0].day).days <= NEAR_DAYS:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def merge_future(candidates: list[Candidate], last_report: date | None, today: date) -> list[FutureDate]:
    """Decide the stored future dates from every source's candidates (all on or after today)."""
    decided: list[FutureDate] = []
    for group in _cluster([c for c in candidates if c.day >= today]):
        by = {c.source: c for c in group}
        company, fin, yf = by.get("company"), by.get("finnhub"), by.get("yfinance")
        if company is not None:
            decided.append(FutureDate(company.day, True, f"confirmed: {company.evidence or 'company announcement'}",
                                      "company", company.timing if company.timing != "unknown" else (yf or fin or company).timing))
        elif fin is not None and yf is not None and fin.day == yf.day:
            decided.append(FutureDate(fin.day, True, "confirmed: Finnhub and Yahoo Finance agree", "finnhub",
                                      fin.timing if fin.timing != "unknown" else yf.timing))
        elif yf is not None:
            note = "estimated (Yahoo Finance)" + (f"; Finnhub says {fin.day.isoformat()}" if fin is not None else "")
            decided.append(FutureDate(yf.day, False, note, "yfinance", yf.timing if yf.timing != "unknown" else (fin.timing if fin else "unknown")))
        elif fin is not None:
            decided.append(FutureDate(fin.day, False, "estimated (Finnhub)", "finnhub", fin.timing))
    if decided and last_report is not None:
        first = decided[0]
        if (first.day - last_report).days > FAR_AFTER_LAST_REPORT_DAYS:
            due = last_report + timedelta(days=QUARTER_DAYS)
            first.note += f"; the last report was {last_report.isoformat()}, so a quarterly report would usually be due around {due.isoformat()}"
    return decided


def resolve_past(
    estimate: date,
    today: date,
    reaction_dates: list[date],
    future_estimates: list[date],
    finnhub_actual_dates: list[date],
    yfinance_reported_dates: list[date],
    edgar_202_dates: list[date],
    checked_at: datetime,
) -> PastResolution:
    """What becomes of an estimated earnings date that passed with no reaction row on it."""
    near_row = [d for d in reaction_dates if abs((d - estimate).days) <= SUPERSEDED_DAYS]
    if near_row:
        d = min(near_row, key=lambda d: abs((d - estimate).days))
        return PastResolution("superseded", f"the quarter was reported on {d.isoformat()}; the {estimate.isoformat()} estimate is removed", d)

    replacing = [d for d in future_estimates if 0 <= (d - estimate).days <= REPLACED_BY_ESTIMATE_DAYS]
    if replacing:
        d = min(replacing)
        return PastResolution("superseded", f"replaced by the {d.isoformat()} estimate", d)

    for label, dates in (("finnhub", finnhub_actual_dates), ("yfinance", yfinance_reported_dates)):
        hit = [d for d in dates if abs((d - estimate).days) <= EVIDENCE_DAYS]
        if hit:
            d = min(hit, key=lambda d: abs((d - estimate).days))
            return PastResolution("reported", f"reported on {d.isoformat()} per {SOURCE_LABELS[label]} (actual EPS)", d)
    hit = [d for d in edgar_202_dates if estimate - timedelta(days=EDGAR_202_LOOKBACK_DAYS) <= d <= today]
    if hit:
        d = min(hit)
        return PastResolution("reported", f"reported on {d.isoformat()} per EDGAR (8-K Item 2.02)", d)

    checked = {
        "finnhub": "no actual EPS within 3 days",
        "yfinance": "no reported EPS within 3 days",
        "edgar": f"no 8-K Item 2.02 filed since {(estimate - timedelta(days=EDGAR_202_LOOKBACK_DAYS)).isoformat()}",
        "checked_at": checked_at.isoformat(),
    }
    return PastResolution("unresolved", f"expected around {estimate.isoformat()}; not confirmed by Finnhub, Yahoo Finance or EDGAR", None, checked)


def level_of(is_confirmed: bool, unresolved_since: date | None) -> str:
    """The level a page shows: 'confirmed', 'estimated' or 'expected_unconfirmed'."""
    if unresolved_since is not None:
        return "expected_unconfirmed"
    return "confirmed" if is_confirmed else "estimated"
