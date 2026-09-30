"""Earnings dates with their confirmation level, from every source, decided one way.

A stored earnings date is one of:
  confirmed    the company set it (an announcement the calendar step fetched) or two independent
               sources name the same day; or the report happened (evidence of an actual EPS or an
               8-K Item 2.02), in which case the date is the report date.
  estimated    one source's estimate (Finnhub or Yahoo Finance); the note names the source.
  unresolved   an estimate whose date passed with no report found by any source: kept as
               "expected around <date>; not confirmed", never labelled past.

merge_future() decides the future dates from the sources' candidates; resolve_past() decides what
becomes of an estimate that passed; beyond_calendar_reach() says which stored dates a calendar source
may not touch. All are pure: the script fetches, these functions decide, the script applies.

Source precedence. Finnhub and Yahoo Finance are calendar sources: they list dates. A stored date
that rests on stronger evidence, a reaction row, an actual EPS, an EDGAR filing or a company
announcement, is never dropped, moved or downgraded because a calendar source lists something else;
a calendar date near it is the same report and is absorbed. A calendar source may only replace or
drop a date that came from a calendar source and that no company confirmed.

An empty or failed fetch is never evidence. A stored calendar estimate is that source's standing word
until the same source returns future dates for the ticker: standing_candidates() puts it back among the
candidates when its source is silent, so it is dropped only when the same source now returns a
different date, or a company announcement contradicts it within the quarterly cadence. Two dates within
SAME_REPORT_DAYS of each other are the same report, never two: when Finnhub and Yahoo Finance disagree
and no one confirmed either, tie_break() decides (a market holiday, half day or weekend loses; else the
stored date stands) and the other day is kept in the note ("Finnhub says ...").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

NEAR_DAYS = 3                        # candidates this close from different sources are the same report (same day: they agree)
SAME_REPORT_DAYS = 60                # two dates closer than this are the same quarterly report; quarters are ~91 days apart
FAR_AFTER_LAST_REPORT_DAYS = 100     # a next date this long after the last report is not the next quarter
QUARTER_DAYS = 91
SUPERSEDED_DAYS = 21                 # a reaction row this close to a past estimate: the quarter was reported
REPLACED_BY_ESTIMATE_DAYS = 14       # a nearer future estimate this close after a past estimate replaces it
EVIDENCE_DAYS = 3                    # an actual EPS this close to the estimate is that report
EDGAR_202_LOOKBACK_DAYS = 5          # 8-K Item 2.02 filed within this many days of the estimate

SOURCE_LABELS = {"finnhub": "Finnhub", "yfinance": "Yahoo Finance", "company": "company announcement"}
CALENDAR_SOURCES = ("finnhub", "yfinance")                 # events.source values a calendar source may replace
AGREEMENT_NOTE = "confirmed: Finnhub and Yahoo Finance agree"   # two calendar sources agreeing is still calendar evidence


@dataclass(frozen=True)
class Candidate:
    day: date
    source: str          # "finnhub" | "yfinance" | "company"
    timing: str = "unknown"
    evidence: str = ""   # for "company": what was fetched, e.g. "8-K Item 7.01 filed 2026-08-28"
    standing: bool = False   # a stored estimate standing in for a source that returned nothing this run


@dataclass
class FutureDate:
    day: date
    confirmed: bool
    note: str            # "confirmed: Finnhub and Yahoo Finance agree" / "estimated (Yahoo Finance); Finnhub says 2026-09-28"
    source: str          # the source whose date was kept
    timing: str = "unknown"


@dataclass(frozen=True)
class StoredDate:
    day: date
    source: str          # events.source value: "finnhub" | "yfinance" | "edgar" | "manual" | ...
    confirmed: bool
    note: str | None
    timing: str = "unknown"


@dataclass
class PastResolution:
    action: str                       # "superseded" | "reported" | "unresolved"
    note: str
    report_date: date | None = None   # for "reported": the evidenced date
    sources_checked: dict = field(default_factory=dict)


def _cluster(cands: list[Candidate]) -> list[list[Candidate]]:
    """Candidates within SAME_REPORT_DAYS of the group's first day are the same report."""
    out: list[list[Candidate]] = []
    for c in sorted(cands, key=lambda c: (c.day, c.source)):
        if out and (c.day - out[-1][0].day).days < SAME_REPORT_DAYS:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def far_note(day: date, last_report: date | None) -> str | None:
    """For a nearest date more than FAR_AFTER_LAST_REPORT_DAYS after the last report: when one is usually due."""
    if last_report is None or (day - last_report).days <= FAR_AFTER_LAST_REPORT_DAYS:
        return None
    due = last_report + timedelta(days=QUARTER_DAYS)
    return f"the last report was {last_report.isoformat()}, so a quarterly report would usually be due around {due.isoformat()}"


def standing_candidates(stored: list[StoredDate], answered: set[str], today: date) -> list[Candidate]:
    """Stored calendar estimates whose source returned no future date this run, as that source's standing word.

    `answered` holds the calendar sources that returned at least one future date for the ticker. A date two
    sources agreed on stands for each of them that is silent. Dates beyond a calendar source's reach are not
    candidates (they are kept outright); past dates are resolved separately.
    """
    out: list[Candidate] = []
    for s in stored:
        if s.day < today or s.source not in CALENDAR_SOURCES:
            continue
        sources = list(CALENDAR_SOURCES) if s.note == AGREEMENT_NOTE else [s.source]
        for src in sources:
            if src not in answered:
                out.append(Candidate(s.day, src, s.timing, standing=True))
    return out


def tie_break(fin: Candidate, yf: Candidate) -> tuple[Candidate, Candidate]:
    """(kept, other) when Finnhub and Yahoo Finance estimate different days for the same quarter and no one
    confirmed either. Neither source is preferred by name: a day the market is closed or closes early (a weekend,
    an NYSE holiday, a half day) loses; otherwise the stored date stands (the standing candidate) and the other
    source's day goes in the note; with neither stored, the nearer day is kept."""
    from app.services.trading_calendar import is_half_day, is_trading_day

    def full_session(c: Candidate) -> bool:
        return is_trading_day(c.day) and not is_half_day(c.day)

    a, b = full_session(fin), full_session(yf)
    if a != b:
        return (fin, yf) if a else (yf, fin)
    if fin.standing != yf.standing:
        return (fin, yf) if fin.standing else (yf, fin)
    return (fin, yf) if fin.day <= yf.day else (yf, fin)


def merge_future(candidates: list[Candidate], last_report: date | None, today: date) -> list[FutureDate]:
    """Decide the stored future dates from every source's candidates (all on or after today).

    Within a report's cluster each source's nearest date is its word; a company announcement wins, then the
    two calendar sources agreeing on a day; two different estimates go to tie_break (a market holiday, half
    day or weekend loses, else the stored date stands), and the other day is kept in the note.
    """
    decided: list[FutureDate] = []
    for group in _cluster([c for c in candidates if c.day >= today]):
        by: dict[str, Candidate] = {}
        for c in group:
            by.setdefault(c.source, c)       # sorted by day: the nearest per source
        company, fin, yf = by.get("company"), by.get("finnhub"), by.get("yfinance")
        if company is not None:
            decided.append(FutureDate(company.day, True, f"confirmed: {company.evidence or 'company announcement'}",
                                      "company", company.timing if company.timing != "unknown" else (yf or fin or company).timing))
        elif fin is not None and yf is not None and fin.day == yf.day:
            decided.append(FutureDate(fin.day, True, AGREEMENT_NOTE, "finnhub",
                                      fin.timing if fin.timing != "unknown" else yf.timing))
        elif fin is not None and yf is not None:
            keep, other = tie_break(fin, yf)
            note = f"estimated ({SOURCE_LABELS[keep.source]}); {SOURCE_LABELS[other.source]} says {other.day.isoformat()}"
            decided.append(FutureDate(keep.day, False, note, keep.source, keep.timing if keep.timing != "unknown" else other.timing))
        elif yf is not None:
            decided.append(FutureDate(yf.day, False, "estimated (Yahoo Finance)", "yfinance", yf.timing))
        elif fin is not None:
            decided.append(FutureDate(fin.day, False, "estimated (Finnhub)", "finnhub", fin.timing))
    if decided:
        note = far_note(decided[0].day, last_report)
        if note:
            decided[0].note += "; " + note
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


def beyond_calendar_reach(stored: StoredDate, reaction_dates: list[date], actual_dates: list[date]) -> str | None:
    """Why a stored earnings date is beyond a calendar source's reach, or None if Finnhub or Yahoo may replace it.

    `reaction_dates` are the ticker's reaction rows; `actual_dates` are dates Finnhub or Yahoo report an actual
    EPS for. Any of these within EVIDENCE_DAYS of the date, an EDGAR (or other non-calendar) source, or a
    company-announcement confirmation puts the date beyond a calendar source's reach.
    """
    if any(abs((d - stored.day).days) <= EVIDENCE_DAYS for d in reaction_dates):
        return "reaction row"
    if any(abs((d - stored.day).days) <= EVIDENCE_DAYS for d in actual_dates):
        return "actual EPS"
    if stored.source == "edgar":
        return "EDGAR"
    if stored.source not in CALENDAR_SOURCES:
        return f"{stored.source} source"
    note = stored.note or ""
    if stored.confirmed and note.startswith("reported on"):
        return "report evidence"          # written only by the evidence paths (resolve_past, catch_up_reports)
    if stored.confirmed and note.startswith("confirmed:") and note != AGREEMENT_NOTE:
        return "company announcement"
    return None


def level_of(is_confirmed: bool, unresolved_since: date | None) -> str:
    """The level a page shows: 'confirmed', 'estimated' or 'expected_unconfirmed'."""
    if unresolved_since is not None:
        return "expected_unconfirmed"
    return "confirmed" if is_confirmed else "estimated"
