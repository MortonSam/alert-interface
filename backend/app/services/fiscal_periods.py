"""A quarter's name as the company gives it in its own filing: the DEI DocumentFiscalYearFocus and DocumentFiscalPeriodFocus
of the 10-Q or 10-K that reports it, which SEC company facts carry as `fy` and `fp` on every fact of that filing.

    "Fiscal Q4 2026, ended Sep 3, 2026"     Micron, whose fiscal year ends around the start of September
    "Q3 2026, ended Sep 30, 2026"           a calendar-year company (JPMorgan)
    "Q3 2026, ended Sep 26, 2026"           a 52/53-week year that ends in late December (Intel): its quarters are the calendar's
    "Fiscal Q3 2026, ended Nov 1, 2025"     a year that ends in January (Walmart calls the year to Jan 2026 fiscal 2026)

A filing's period is the latest end date among its duration facts. A 10-K's period ("FY") is the year's fourth quarter. "Fiscal"
is left out when the company's quarter is the calendar's: the same quarter number and year as the calendar quarter of the
date FISCAL_SLACK_DAYS before its end (a 52/53-week year ends up to a week either side of Dec 31). A quarter no filing names
reads "the quarter ended Sep 3, 2026"; nothing here guesses a fiscal label.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.briefing import fmt_date

FISCAL_PERIODS_VERSION = 2               # 2 (2026-10-19): self-contradicting filings and doubly claimed names left out (Dell)
FISCAL_SLACK_DAYS = 10            # a 52/53-week quarter ends up to a week past the calendar quarter's end
MATCH_DAYS = 7                    # a stored period end within this many days of a filing's period takes that filing's name
FORMS = ("10-Q", "10-K")


def period_map(facts: dict) -> dict[str, list]:
    """Pure: {period end ISO: [fiscal year, "Q1" | "Q2" | "Q3" | "Q4"]} from company facts, one entry per 10-Q or 10-K whose facts
    agree on a single fy and fp. Left out, so the quarter reads by its end date: a filing that names two periods, a 10-Q tagged "FY"
    or a 10-K tagged a quarter, a period end two filings name differently, and a name two period ends both claim."""
    by_accn: dict[str, dict] = {}
    for tax in (facts.get("facts") or {}).values():
        for concept in tax.values():
            for unit in (concept.get("units") or {}).values():
                for e in unit:
                    if e.get("form") not in FORMS or not e.get("accn") or not e.get("fy") or not e.get("fp"):
                        continue
                    a = by_accn.setdefault(e["accn"], {"names": set(), "end": ""})
                    a["names"].add((int(e["fy"]), str(e["fp"]), e["form"]))
                    if e.get("start") and e.get("end"):
                        a["end"] = max(a["end"], e["end"])
    out: dict[str, list] = {}
    for a in by_accn.values():
        if len(a["names"]) != 1 or not a["end"]:
            continue
        fy, fp, form = next(iter(a["names"]))
        if (form == "10-Q") == (fp == "FY"):
            continue                    # a 10-Q tagged "FY" or a 10-K tagged a quarter contradicts itself (Dell's 2023 10-Qs say "FY")
        q = "Q4" if fp == "FY" else fp
        if q in ("Q1", "Q2", "Q3", "Q4"):
            out.setdefault(a["end"][:10], set()).add((fy, q))
    named = {end: next(iter(v)) for end, v in out.items() if len(v) == 1}
    seen: dict[tuple, list[str]] = {}
    for end, name in named.items():
        seen.setdefault(name, []).append(end)
    return {end: list(name) for end, name in sorted(named.items()) if len(seen[name]) == 1}     # a name two periods claim names neither


def _find(periods: dict | None, end: date) -> tuple[int, str] | None:
    if not periods or not end:
        return None
    hit = periods.get(end.isoformat())
    if hit:
        return int(hit[0]), hit[1]
    near = [(abs((date.fromisoformat(k) - end).days), v) for k, v in periods.items()]
    near = [x for x in near if x[0] <= MATCH_DAYS]
    if not near:
        return None
    v = min(near, key=lambda x: x[0])[1]
    return int(v[0]), v[1]


def calendar_like(fy: int, q: str, end: date) -> bool:
    """Pure: the company's quarter is the calendar's quarter (same number, same year)."""
    d = end - timedelta(days=FISCAL_SLACK_DAYS)
    return fy == d.year and int(q[1]) == (d.month - 1) // 3 + 1


def quarter_name(periods: dict | None, end: date) -> str | None:
    """"fiscal Q4 2026" or "Q3 2026" (lower case, for the middle of a sentence), None when no filing names the quarter."""
    hit = _find(periods, end)
    if not hit:
        return None
    fy, q = hit
    return f"{q} {fy}" if calendar_like(fy, q, end) else f"fiscal {q} {fy}"


def cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def quarter(periods: dict | None, end: date) -> str:
    """In a sentence: "fiscal Q4 2026, ended Sep 3, 2026", "Q3 2026, ended Sep 30, 2026" or "the quarter ended Sep 3, 2026"."""
    name = quarter_name(periods, end)
    return f"{name}, ended {fmt_date(end)}" if name else f"the quarter ended {fmt_date(end)}"


def quarter_label(periods: dict | None, end: date) -> str:
    """As a label: "Fiscal Q4 2026, ended Sep 3, 2026", "Q3 2026, ended Sep 30, 2026", "Quarter ended Sep 3, 2026"."""
    return cap(quarter(periods, end).removeprefix("the "))


def through(periods: dict | None, end: date) -> str:
    """"through fiscal Q4 2026", "through Q3 2026", "through the quarter ended Sep 3, 2026"."""
    name = quarter_name(periods, end)
    return f"through {name}" if name else f"through the quarter ended {fmt_date(end)}"


def four_label(periods: dict | None, end: date) -> str:
    """"Last four quarters, through fiscal Q4 2026"."""
    return f"Last four quarters, {through(periods, end)}"


def year(periods: dict | None, end: date) -> str:
    """A fiscal year in a sentence: "fiscal 2026, ended Sep 3, 2026" or, for a calendar-year company, "the year ended Dec 31, 2025"."""
    hit = _find(periods, end)
    if hit and hit[1] == "Q4" and not calendar_like(*hit, end):
        return f"fiscal {hit[0]}, ended {fmt_date(end)}"
    return f"the year ended {fmt_date(end)}"
