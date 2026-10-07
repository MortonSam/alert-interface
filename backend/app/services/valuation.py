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
SECTOR_COVERAGE_MIN = 0.90        # a sector median shows only when this share of the sector's active tickers has a fresh window
NOT_MEANINGFUL_REASON = "lost money over the last four quarters"
REFRESH_AFTER_REPORT_DAYS = 100   # quarters are re-read from XBRL while a report this recent may not have landed in XBRL yet
NEWER_REPORT_GRACE_DAYS = 20      # a report dated more than this many days after the latest XBRL quarter end is a newer quarter
MAX_QUARTER_GAP_DAYS = 125        # the release quarter must directly follow the newest XBRL quarter; a longer gap means a quarter is missing
PERIOD_END_MAX_DAYS = 120         # a release reports a quarter that ended within this many days before the report

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
_MONEY = r"\$?\s?\(?-?\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?\)?"
# "GAAP net income of $37.70 billion, or $32.87 per diluted share" (the quarter's highlight comes before the year's)
_PROSE = re.compile(rf"GAAP\s+net\s+(?:income|earnings|loss)\b.{{0,80}}?,\s*or\s+(?:a\s+(?:loss|net loss)\s+of\s+)?\$\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*(?:\.\d{{1,2}})?\)?)\s+per\s+diluted\s+share", re.I)
# "GAAP diluted earnings per share $ 32.87 $ 24.67 ..." / "Diluted earnings per share 32.87 24.67 ..." (first column is the current quarter)
_ROW = re.compile(rf"(?<![A-Za-z-])(?:GAAP\s+)?diluted\s+(?:net\s+)?(?:earnings|income|loss)\s+per\s+(?:common\s+)?share(?:\s*\(\d\))?\s*(?:attributable[^$\d]{{0,80}})?[:\s]*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
_ROW2 = re.compile(rf"earnings\s+per\s+share[^A-Za-z]{{0,20}}basic[^A-Za-z]{{0,40}}diluted\s*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
_NON_GAAP_NEAR = re.compile(r"non-?\s?gaap|adjusted|pro\s?forma|excluding|\bcore\b|operating (?:income|earnings)|underlying|normali[sz]ed", re.I)
_NUM = r"(\(?-?\d{1,4}(?:,\d{3})*\.\d{1,2}\)?)"
# other phrasings, tried after _PROSE and _ROW, in this order
_PROSE_ANY = re.compile(rf"\b(?:net\s+(?:income|earnings|loss)|earnings|income)\b[^;]{{0,120}}?,?\s+or\s+(?:a\s+(?:loss|net loss)\s+of\s+)?\$\s?{_NUM}\s+per\s+diluted\s+(?:common\s+)?share", re.I)
_LABELLED = re.compile(rf"(?<![A-Za-z-])(?:earnings\s+per\s+share:?\s*GAAP:?|GAAP\s+(?:diluted\s+)?EPS(?:\s+of|\s+was|:)?|diluted\s+EPS(?:\s+of|\s+was|:)?|GAAP\s+earnings\s+per\s+(?:diluted\s+)?share(?:\s+of|\s+was|:)?)\s*\$\s?{_NUM}", re.I)
_ROW_DASH = re.compile(rf"(?:net\s+)?(?:earnings|income)\s+per\s+(?:common\s+)?share\s*[—–-]+\s*diluted\s*\$?\s?{_NUM}", re.I)
_ROW_NET = re.compile(rf"net\s+(?:income|earnings)\s+per\s+(?:common\s+)?(?:diluted\s+)?share[^$\d]{{0,30}}diluted\s*\$?\s?{_NUM}", re.I)
_PER_DILUTED = re.compile(rf"\$\s?{_NUM}\s+per\s+diluted\s+(?:common\s+)?share", re.I)
_PER_SHARE = re.compile(rf"\bnet\s+income\b[^;]{{0,120}}?,?\s+or\s+\$\s?{_NUM}\s+per\s+share", re.I)       # insurers' "per share net income": diluted by their statements
# a figure inside an outlook is never the quarter's result: a guidance word nearby, or a range to a second amount right after it
_GUIDANCE_NEAR = re.compile(r"outlook|guidance|expect|forecast|anticipat|projected|target|(?:fiscal|fy)\s*'?\d{2,4}\s+(?:guidance|outlook)|next\s+(?:quarter|year)|first\s+quarter\s+of\s+fiscal", re.I)
_RANGE_AFTER = re.compile(r"^\s*(?:to|[–—-]|±)\s*\$?\s?\d", re.I)
_PERIOD_END = re.compile(rf"(?:(?:three|3)\s+months|\d{{1,2}}\s+weeks|quarter|qtr\.?|fiscal\s+quarter|quarterly\s+period)\s+ended\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)
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
    the income statement's "Earnings per share: Basic … Diluted …" row; a labelled figure ("Earnings per Share: GAAP: $Y",
    "Diluted EPS $Y"); a dash or net-income row ("Earnings per share—diluted $Y"); a net-income sentence without the word
    GAAP ("net income of $X, or $Y per diluted share"); the first "$Y per diluted share"; and, last, an insurer's "net income
    of $X, or $Y per share". Anything preceded by non-GAAP, adjusted, core, pro forma or operating is skipped. Returns
    {eps, how, evidence, period_end} or None when no GAAP diluted figure can be read."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    period_end = None
    for m in list(_PERIOD_END.finditer(flat)) + list(_QTR_HEADER.finditer(flat)):
        d = _to_date(m)
        # the quarter a release reports ended within PERIOD_END_MAX_DAYS before the report; an older date is a comparison period
        if d and (report_date is None or 0 <= (report_date - d).days <= PERIOD_END_MAX_DAYS):
            period_end = d
            break
    hit = _PROSE.search(flat)
    if hit and not _GUIDANCE_NEAR.search(flat[max(0, hit.start() - 200):hit.start()]):
        return {"eps": _num(hit.group(1)), "how": "highlights sentence", "evidence": flat[max(0, hit.start() - 20):hit.end() + 10].strip(), "period_end": period_end}
    attempts = ((_ROW, "diluted EPS row", 12), (_ROW2, "income statement EPS row", 12), (_LABELLED, "labelled GAAP EPS", 40), (_ROW_DASH, "EPS row, dash diluted", 12),
                (_ROW_NET, "net income per share row", 12), (_PROSE_ANY, "net income sentence", 12), (_PER_DILUTED, "per diluted share", 80), (_PER_SHARE, "per share net income sentence", 12))
    for pattern, how, back in attempts:
        for hit in pattern.finditer(flat):
            before = flat[max(0, hit.start() - back):hit.start()] if back else ""
            if _NON_GAAP_NEAR.search(before) or _NON_GAAP_NEAR.search(hit.group(0)):
                continue
            if _GUIDANCE_NEAR.search(flat[max(0, hit.start() - 200):hit.start()]) or _RANGE_AFTER.search(flat[hit.end():hit.end() + 12]):
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
        rel_end = release.get("period_end") or latest_report
        if (rel_end - three[-1]["end"]).days > MAX_QUARTER_GAP_DAYS:
            return None, f"XBRL is more than one quarter behind the latest report (through {three[-1]['end'].isoformat()}, release quarter ended {rel_end.isoformat()})"
        rel = {"end": rel_end, "start": three[-1]["end"] + timedelta(days=1), "eps": float(release["eps"]), "filed": latest_report,
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


def snapshot(price: float | None, quarters: list[dict], latest_report: date | None, release: dict | None, as_of: date) -> dict:
    """Pure: what the nightly stores for one ticker: status ok (a P/E), not_meaningful (a fresh window whose trailing EPS is zero
    or negative) or missing (no fresh window), with the reason, the window and its four quarters."""
    four, why = fresh_window(quarters, latest_report, release, as_of)
    base = {"status": "missing", "reason": None, "trailing_eps": None, "pe": None, "window_start": None, "window_end": None, "window_source": None,
            "latest_report": latest_report, "quarters": None}
    if four is None:
        return {**base, "reason": why}
    total = round(sum(q["eps"] for q in four), 4)
    base.update(window_start=four[0]["start"], window_end=four[-1]["end"], window_source=why, trailing_eps=total,
                quarters=[{**q, "end": q["end"].isoformat(), "start": q["start"].isoformat(), "filed": q["filed"].isoformat()} for q in four])
    if price is None:
        return {**base, "reason": "no stored close"}
    if total <= 0:
        return {**base, "status": "not_meaningful", "reason": NOT_MEANINGFUL_REASON}
    return {**base, "status": "ok", "pe": round(price / total, 2)}


def sector_summary(statuses: list[tuple[str, float | None]], active: int) -> dict:
    """Pure: the sector median over tickers with a P/E, shown only when fresh windows (ok or not meaningful) cover at least
    SECTOR_COVERAGE_MIN of the sector's active tickers. `statuses` are (status, pe) per ticker with a snapshot."""
    fresh = sum(1 for s, _ in statuses if s in ("ok", "not_meaningful"))
    values = sorted(p for s, p in statuses if s == "ok" and p is not None)
    coverage = fresh / active if active else 0.0
    shown = active > 0 and coverage >= SECTOR_COVERAGE_MIN and bool(values)
    reason = None if shown else (f"only {fresh} of {active} active tickers have a fresh P/E window ({coverage:.0%}; {SECTOR_COVERAGE_MIN:.0%} needed)" if active else "no active tickers")
    return {"median_pe": round(statistics.median(values), 2) if values else None, "with_pe": len(values), "fresh": fresh, "active": active, "shown": shown, "reason": reason}


def needs_refresh(stored_quarters: list[dict], latest_report: date | None, today: date) -> bool:
    """Pure: re-read XBRL when nothing is stored, or when a report in the last REFRESH_AFTER_REPORT_DAYS is newer than the
    stored quarters hold (its 10-Q or 10-K may have landed since the last read)."""
    if not stored_quarters:
        return True
    if latest_report is None or (today - latest_report).days > REFRESH_AFTER_REPORT_DAYS:
        return False
    return newer_quarter_reported(stored_quarters, latest_report)
