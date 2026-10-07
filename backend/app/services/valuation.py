"""Trailing P/E from filings (report only until approved; nothing displays).

The trailing window is the latest four reported quarters of GAAP diluted EPS. Three sources, in order of authority: XBRL
company facts (quarterly EarningsPerShareDiluted facts, the fourth quarter derived from the 10-K's annual figure when only
that is filed), and, when the company has reported a quarter newer than XBRL holds, the GAAP diluted EPS parsed from that
quarter's earnings release (the Item 2.02 8-K's EX-99.1, stored in release_eps with the filing as its receipt). A window
that does not include the company's latest reported quarter is never used: when the latest quarter cannot be read, there
is no P/E. Every P/E is stated with the period its four quarters cover.

History: each session's close over the four quarters filed by that day (point in time). Sessions where trailing EPS is
negative or below MIN_EARNINGS_YIELD of the price (a P/E above 100) are excluded and counted; the summary is the median
and the share of sessions today's P/E sits above, never the minimum or maximum.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

QUARTER_DAYS = (80, 100)          # a quarterly EPS fact covers a period this long
YEAR_DAYS = (350, 380)            # an annual one
MIN_EARNINGS_YIELD = 0.01         # trailing EPS below 1% of price (P/E above 100) is excluded from history
RANGE_YEARS = 5
RELEASE_TOLERANCE = 0.01          # a release figure this far from the XBRL figure for the same quarter is flagged
NEWER_REPORT_GRACE_DAYS = 20      # a report dated more than this many days after the latest XBRL quarter end is a newer quarter

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
_MONEY = r"\$?\s?\(?-?\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?\)?"
# "GAAP net income of $37.70 billion, or $32.87 per diluted share" (the quarter's highlight comes before the year's)
_PROSE = re.compile(rf"GAAP\s+net\s+(?:income|earnings|loss)\b.{{0,80}}?,\s*or\s+(?:a\s+(?:loss|net loss)\s+of\s+)?\$\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*(?:\.\d{{1,2}})?\)?)\s+per\s+diluted\s+share", re.I)
# "GAAP diluted earnings per share $ 32.87 $ 24.67 ..." / "Diluted earnings per share 32.87 24.67 ..." (first column is the current quarter)
_ROW = re.compile(rf"(?<![A-Za-z-])(?:GAAP\s+)?diluted\s+(?:net\s+)?(?:earnings|income|loss)\s+per\s+(?:common\s+)?share(?:\s*\(\d\))?\s*(?:attributable[^$\d]{{0,80}})?[:\s]*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
_ROW2 = re.compile(rf"earnings\s+per\s+share[^A-Za-z]{{0,20}}basic[^A-Za-z]{{0,40}}diluted\s*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
_NON_GAAP_NEAR = re.compile(r"non-?\s?gaap|adjusted|pro\s?forma|excluding", re.I)
_PERIOD_END = re.compile(rf"(?:(?:three|3)\s+months|quarter|qtr\.?|fiscal\s+quarter|quarterly\s+period)\s+ended\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)
_QTR_HEADER = re.compile(rf"(?:[1-4](?:st|nd|rd|th)\s+Qtr\.?|Q[1-4])[^A-Za-z]{{0,40}}(?:[1-4](?:st|nd|rd|th)\s+Qtr\.?|Q[1-4]|Year\s+Ended|Twelve\s+Months)?[^A-Za-z]{{0,40}}(?:Year\s+Ended\s+)?({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)


def _to_date(m: re.Match, g: int = 1) -> date | None:
    try:
        return date(int(m.group(g + 2)), [x.lower() for x in _MONTHS.split("|")].index(m.group(g).lower()) + 1, int(m.group(g + 1)))
    except ValueError:
        return None


def _num(s: str) -> float:
    s = s.replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    v = float(s.strip("()"))
    return -v if neg else v


def parse_release_eps(text: str, report_date: date | None = None) -> dict | None:
    """Pure: the quarter's GAAP diluted EPS stated in an earnings release, with how it was read.

    Tries, in order: the highlights sentence "GAAP net income of $X, or $Y per diluted share" (the first such sentence is
    the quarter; the year's follows); the "GAAP diluted earnings per share" table row (first column, the current quarter);
    the income statement's "Earnings per share: Basic … Diluted …" row. A row whose preceding words say non-GAAP, adjusted
    or pro forma is skipped. Returns {eps, how, evidence, period_end} or None when no GAAP diluted figure can be read."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    period_end = None
    m = _PERIOD_END.search(flat)
    if m:
        period_end = _to_date(m)
    else:
        m = _QTR_HEADER.search(flat)
        if m:
            period_end = _to_date(m)
    hit = _PROSE.search(flat)
    if hit:
        return {"eps": _num(hit.group(1)), "how": "highlights sentence", "evidence": flat[max(0, hit.start() - 20):hit.end() + 10].strip(), "period_end": period_end}
    for pattern, how in ((_ROW, "diluted EPS row"), (_ROW2, "income statement EPS row")):
        for hit in pattern.finditer(flat):
            before = flat[max(0, hit.start() - 12):hit.start()]          # "Non-GAAP " / "Adjusted " right before the row's label
            if _NON_GAAP_NEAR.search(before) or _NON_GAAP_NEAR.search(hit.group(0)):
                continue
            return {"eps": _num(hit.group(1)), "how": how, "evidence": flat[max(0, hit.start() - 20):hit.end() + 40].strip(), "period_end": period_end}
    return None


def eps_quarters(facts: dict) -> list[dict]:
    """Pure: quarterly GAAP diluted EPS from a companyfacts document, oldest first: the quarterly facts, plus the fourth
    quarter derived as the fiscal year's annual figure less the three quarters inside it. One value per period end, the
    latest filed wins. Each: {end, start, eps, filed, form, derived, source}."""
    series = (facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", []))
    quarters: dict[date, dict] = {}
    annual: list[dict] = []
    for e in series:
        try:
            start, end, filed = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), date.fromisoformat(e["filed"])
        except (KeyError, ValueError):
            continue
        days = (end - start).days
        row = {"end": end, "start": start, "eps": float(e["val"]), "filed": filed, "form": e.get("form", ""), "derived": False, "source": "xbrl"}
        if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
            if end not in quarters or filed >= quarters[end]["filed"]:
                quarters[end] = row
        elif YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
            annual.append(row)
    for a in annual:
        if a["end"] in quarters:
            continue
        inside = [q for q in quarters.values() if a["start"] <= q["start"] and q["end"] < a["end"]]
        if len(inside) == 3:
            quarters[a["end"]] = {"end": a["end"], "start": max(q["end"] for q in inside) + timedelta(days=1), "eps": round(a["eps"] - sum(q["eps"] for q in inside), 4),
                                  "filed": a["filed"], "form": a["form"], "derived": True, "source": "xbrl"}
    return sorted(quarters.values(), key=lambda q: q["end"])


def trailing_four(quarters: list[dict], as_of: date, known_by: date | None = None) -> list[dict] | None:
    """Pure: the four most recent quarters ending on or before as_of and filed by known_by (point in time), oldest first."""
    known_by = known_by or as_of
    eligible = [q for q in quarters if q["end"] <= as_of and q["filed"] <= known_by]
    return eligible[-4:] if len(eligible) >= 4 else None


def newer_quarter_reported(quarters: list[dict], latest_report: date | None) -> bool:
    """Pure: the company reported a quarter XBRL does not hold yet (the latest report is well after the newest XBRL quarter end
    and after that quarter's filing)."""
    if latest_report is None or not quarters:
        return False
    last = quarters[-1]
    return latest_report > last["filed"] and (latest_report - last["end"]).days > NEWER_REPORT_GRACE_DAYS


def fresh_window(quarters: list[dict], latest_report: date | None, release: dict | None, as_of: date) -> tuple[list[dict] | None, str]:
    """Pure: (the four quarters a shown P/E may rest on, why or why not). The window must include the latest reported quarter:
    XBRL alone when it holds that quarter; three XBRL quarters plus the stored release figure when the release is newer; None
    when the newest quarter cannot be read."""
    if newer_quarter_reported(quarters, latest_report):
        if release is None or release.get("eps") is None:
            return None, f"the {latest_report.isoformat()} report is newer than XBRL (through {quarters[-1]['end'].isoformat()}) and its release EPS is not stored"
        three = [q for q in quarters if q["end"] <= as_of][-3:]
        if len(three) < 3:
            return None, "fewer than three XBRL quarters before the release quarter"
        rel = {"end": release.get("period_end") or latest_report, "start": three[-1]["end"] + timedelta(days=1), "eps": float(release["eps"]), "filed": latest_report,
               "form": f"earnings release 8-K {release.get('accession') or ''}".strip(), "derived": False, "source": "release"}
        return three + [rel], "three XBRL quarters plus the release quarter"
    four = trailing_four(quarters, as_of)
    if four is None:
        return None, "fewer than four reported quarters in XBRL"
    return four, "XBRL holds the latest reported quarter"


def pe(price: float | None, four: list[dict] | None) -> float | None:
    if price is None or not four:
        return None
    total = sum(q["eps"] for q in four)
    return round(price / total, 2) if total > 0 else None


def period_label(four: list[dict]) -> str:
    return f"{four[0]['start'].isoformat()} to {four[-1]['end'].isoformat()}"


def pe_history(bars: list[tuple[date, float]], quarters: list[dict], current: float | None) -> dict:
    """Pure: {sessions, excluded, median, share_above, first, last} over the bars: each day's close over the four quarters
    filed by that day; a day with trailing EPS at or below zero or below MIN_EARNINGS_YIELD of the close is excluded."""
    kept: list[float] = []
    excluded = 0
    first = last = None
    for d, close in bars:
        four = trailing_four(quarters, d, d)
        if four is None:
            continue
        total = sum(q["eps"] for q in four)
        if total <= 0 or total < MIN_EARNINGS_YIELD * close:
            excluded += 1
            continue
        kept.append(round(close / total, 2))
        first = first or d
        last = d
    out = {"sessions": len(kept), "excluded": excluded, "median": round(statistics.median(kept), 1) if kept else None, "first": first, "last": last, "share_above": None}
    if kept and current is not None:
        out["share_above"] = round(sum(1 for v in kept if v < current) / len(kept) * 100)
    return out


def release_difference(release_eps: float, xbrl_eps: float) -> tuple[float, bool]:
    """Pure: (difference, flagged) between a stored release figure and the XBRL figure for the same quarter."""
    diff = round(release_eps - xbrl_eps, 4)
    return diff, abs(diff) > RELEASE_TOLERANCE
