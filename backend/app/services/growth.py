"""Revenue and GAAP diluted EPS growth, quarter against the same quarter a year earlier, for the last four reported quarters.

A figure is used only when two readers agree: the XBRL company-facts value as the company first filed it, and either that
quarter's own earnings release (Item 2.02 8-K exhibit: release EPS by parse_release_eps, revenue by parse_release_revenue) or,
when no release can be read, the same figure as restated in a later filing's comparative column. A disagreement is logged and
never shown. Growth is held, with the reason, when a spin-off, merger, share-exchange acquisition or rename-merge is recorded
inside the comparison window (as the P/E is). A move between a loss and a profit is written in words, never as a percentage.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app.services.valuation import (
    ACTION_VERBS, EPS_FACT_MAX, QUARTER_DAYS, YEAR_DAYS, _current_column, drop_renames_explained, header_order, split_factor,
)

GROWTH_VERSION = 1
QUARTERS_SHOWN = 4
YEAR_AGO_DAYS = (350, 380)          # the same quarter a year earlier ends this many days before
EPS_TOLERANCE = 0.01                # two EPS readings agree to the cent
REVENUE_TOLERANCE = 0.001           # two XBRL revenue readings agree to 0.1% (a restated comparative may round differently)

# Revenue tags tried in order, by GICS sector: banks report net revenue after interest expense, insurers and REITs report
# "Revenues", most others the ASC 606 contract-revenue tag (or SalesRevenueNet before 2018).
_GENERAL = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"]
REVENUE_TAGS: dict[str, list[str]] = {
    "Financials": ["RevenuesNetOfInterestExpense", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                   "InterestAndDividendIncomeOperating"],
    "Real Estate": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "OperatingLeasesIncomeStatementLeaseRevenue"],
    "Utilities": ["Revenues", "RegulatedAndUnregulatedOperatingRevenue", "RevenueFromContractWithCustomerExcludingAssessedTax",
                  "ElectricUtilityRevenue"],
}


def revenue_tags(sector: str | None) -> list[str]:
    return REVENUE_TAGS.get(sector or "", _GENERAL) + [t for t in _GENERAL if t not in REVENUE_TAGS.get(sector or "", _GENERAL)]


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def quarter_readings(entries: list[dict], per_share: bool, splits=None) -> dict[date, dict]:
    """Pure: {period end: {start, as_filed, as_filed_on, form, restated, restated_on, derived}} from one tag's facts. as_filed is the
    value in the earliest filing that reported the quarter; restated is the value in the latest later filing that repeats it (a
    comparative column), when one does. A fourth quarter no filing states alone is derived: the year less the three quarters inside
    it, as first filed. Per-share values are restated to today's share basis across `splits`."""
    by_end: dict[date, list[tuple[date, float, date, str]]] = {}
    annual: dict[tuple[date, date], list[tuple[date, float, str]]] = {}
    for e in entries:
        start, end, filed = _d(e.get("start")), _d(e.get("end")), _d(e.get("filed"))
        if not (start and end and filed) or e.get("val") is None:
            continue
        val = float(e["val"])
        if per_share:
            if abs(val) > EPS_FACT_MAX:
                continue
            val = round(val / split_factor(filed, splits)[0], 4)
        days = (end - start).days
        if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
            by_end.setdefault(end, []).append((filed, val, start, e.get("form", "")))
        elif YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
            annual.setdefault((start, end), []).append((filed, val, e.get("form", "")))
    out: dict[date, dict] = {}
    for end, rows in by_end.items():
        rows.sort()
        first, last = rows[0], rows[-1]
        out[end] = {"start": first[2], "as_filed": first[1], "as_filed_on": first[0], "form": first[3], "derived": False,
                    "restated": last[1] if last[0] > first[0] else None, "restated_on": last[0] if last[0] > first[0] else None}
    for (start, end), rows in annual.items():
        if end in out:
            continue
        inside = [q for e2, q in out.items() if start <= q["start"] and e2 < end and not q["derived"]]
        if len(inside) != 3:
            continue
        rows.sort()
        year_first = rows[0][1]
        q_start = max(e2 for e2, q in out.items() if start <= q["start"] and e2 < end) + timedelta(days=1)
        out[end] = {"start": q_start, "as_filed": round(year_first - sum(q["as_filed"] for q in inside), 4 if per_share else 0),
                    "as_filed_on": rows[0][0], "form": rows[0][2], "derived": True, "restated": None, "restated_on": None}
    return out


def revenue_by_tag(us_gaap: dict, sector: str | None) -> list[tuple[str, dict[date, dict]]]:
    """Pure: [(tag, quarter readings)] in the sector's order, for every tag the company has filed."""
    out = []
    for tag in revenue_tags(sector):
        entries = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        if entries:
            out.append((tag, quarter_readings(entries, per_share=False)))
    return out


def tag_for_pair(by_tag: list[tuple[str, dict[date, dict]]], end: date) -> tuple[str | None, dict[date, dict], date | None]:
    """Pure: (tag, its quarters, the year-ago end) for one comparison: the first tag in the sector's order that carries both the
    quarter and the same quarter a year earlier, so both figures are the same measure; else the first that carries the quarter."""
    first = None
    for tag, q in by_tag:
        if end in q:
            ya = year_ago(end, q)
            if ya:
                return tag, q, ya
            first = first or (tag, q, None)
    return first or (None, {}, None)


def pick_revenue_tag(us_gaap: dict, sector: str | None, needed: list[date]) -> tuple[str | None, dict[date, dict]]:
    """Pure: the first tag in the sector's order whose quarters cover every period end in `needed` (or the most of them)."""
    best: tuple[int, str | None, dict] = (-1, None, {})
    for tag in revenue_tags(sector):
        entries = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        if not entries:
            continue
        q = quarter_readings(entries, per_share=False)
        covered = sum(1 for d in needed if d in q)
        if covered == len(needed) and needed:
            return tag, q
        if covered > best[0]:
            best = (covered, tag, q)
    return best[1], best[2]


def latest_quarters(quarters: dict[date, dict], n: int = QUARTERS_SHOWN) -> list[date]:
    return sorted(quarters)[-n:]


def year_ago(end: date, quarters: dict[date, dict]) -> date | None:
    cands = [d for d in quarters if YEAR_AGO_DAYS[0] <= (end - d).days <= YEAR_AGO_DAYS[1]]
    return min(cands, key=lambda d: abs((end - d).days - 365)) if cands else None


# ── the release's revenue line ───────────────────────────────────────────────────────────────────────────────────────────────

_REV_LABELS = [r"total\s+net\s+revenues?", r"total\s+revenues?(?:\s+and\s+other\s+income)?", r"net\s+revenues?", r"total\s+net\s+sales",
               r"net\s+sales", r"revenues?", r"sales"]
_AMOUNT = r"\$?\s?(\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?\d+\.\d+\)?|\(?\d{2,}\)?)"
_SCALE = re.compile(r"\(\s*(?:dollars\s+|\$\s*)?in\s+(millions|thousands|billions)|(?:in|\$)\s+(millions|thousands|billions)\b", re.I)


_PROSE_REV = re.compile(r"(?<![A-Za-z])(?:(reported|total|net|gaap|quarterly|consolidated)\s+)?(?:net\s+)?revenues?\s+(?:of|was|were|totaled)\s+"
                        r"\$\s?(\d[\d,]*(?:\.\d+)?)\s+(billion|million)", re.I)
_SEGMENT_BEFORE = re.compile(r"(?:[A-Z][\w&.'-]*\s*)$")


def _prose_revenue(flat: str) -> dict | None:
    """The company-level revenue sentence ("Reported revenue of $49.8 billion", "Revenue of $11.32 billion"): never a segment's
    ("Markets revenue reached ...", "In the CIB, revenue grew"), never guidance or a year's."""
    for m in _PROSE_REV.finditer(flat):
        if not m.group(1):
            prev = flat[max(0, m.start() - 30):m.start()]
            if _SEGMENT_BEFORE.search(prev.rstrip()) and not re.search(r"(?:^|[.;:•\n])\s*$", prev):
                continue                         # a capitalised word right before "revenue" names a segment or product
        context = flat[max(0, m.start() - 160):m.end() + 40]
        if re.search(r"guidance|outlook|expect|full[- ]year|fiscal[- ]year|year[- ]to[- ]date|twelve months|annual", context, re.I):
            continue
        near = flat[max(0, m.start() - 60):m.start()]
        if re.search(r"\bfiscal\s+(?:year\s+)?(?:20)?\d{2}\b|\bFY\s?'?\d{2}\b|\b20\d{2}\s*$", near, re.I) and not re.search(r"quarter|\bQ[1-4]\b", near, re.I):
            continue                             # "Fiscal 2025 revenue of $37.38 billion" is the year's (MU); "fourth quarter of fiscal 2025" stays
        num = float(m.group(2).replace(",", ""))
        return {"raw": m.group(2), "value": num * (1e9 if m.group(3).lower() == "billion" else 1e6), "number": num,
                "scale": m.group(3).lower() + "s", "how": "revenue sentence", "evidence": flat[max(0, m.start() - 10):m.end() + 10]}
    return None


def parse_release_revenue(text: str) -> dict | None:
    """Pure: the quarter's revenue from an earnings release's income statement: the first row labelled total net revenue, total
    revenues, net revenues, net sales, revenues or sales (in that order of preference) carrying at least two amounts, never a cost
    line ("cost of revenues") or a percentage; the current column per the heading before the row (valuation.header_order). Returns
    {value (in dollars when the table states its unit), raw, scale, how, evidence} or None."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    prose = _prose_revenue(flat)
    if prose:
        return prose
    for label in _REV_LABELS:
        pat = re.compile(rf"(?<![A-Za-z])(?<!of\s)(?<!cost\sof\s)({label})(?:\s*\(\w\))?[:\s]+{_AMOUNT}(?!\s*%)\s+{_AMOUNT}(?!\s*%)", re.I)
        for m in pat.finditer(flat):
            before = flat[max(0, m.start() - 40):m.start()].lower()
            if re.search(r"cost\s+of\s*$|of\s*$|growth\s*$|per\s*$", before) or re.search(r"guidance|outlook", flat[max(0, m.start() - 200):m.start()], re.I):
                continue
            first, second = m.group(2), m.group(3)
            raw = second if header_order(flat, m.start()) == "prior-first" else first
            scale_m = None
            for sm in _SCALE.finditer(flat[:m.start()]):
                scale_m = sm
            unit = (scale_m.group(1) or scale_m.group(2)).lower() if scale_m else None
            factor = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}.get(unit, None)
            num = float(raw.replace(",", "").replace("$", "").strip("()"))
            return {"raw": raw, "value": num * factor if factor else None, "number": num, "scale": unit, "how": m.group(1).lower(),
                    "evidence": flat[max(0, m.start() - 10):m.end() + 10]}
    return None


def revenue_agrees(xbrl: float, release: dict) -> bool:
    """Pure: the release's figure is the XBRL figure at the release's precision: in the unit the table states, or, with no unit
    stated, in whichever of dollars, thousands, millions or billions makes them match."""
    raw = release["raw"].strip("()$ ")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    for factor in ([{"thousands": 1e3, "millions": 1e6, "billions": 1e9}[release["scale"]]] if release.get("scale") in ("thousands", "millions", "billions") else [1, 1e3, 1e6, 1e9]):
        if abs(release["number"] * factor - xbrl) <= 0.5 * factor * 10 ** -decimals + 1:
            return True
    return False


# ── agreement, growth and words ──────────────────────────────────────────────────────────────────────────────────────────────

def confirm(metric: str, q: dict, release_value) -> tuple[float | None, str, str | None]:
    """Pure: (the agreed figure or None, which readers agreed, why not). The release is the second reader when it states the
    figure; otherwise the later filing's restated comparative."""
    x = q["as_filed"]
    if release_value is not None:
        ok = abs(x - release_value) <= EPS_TOLERANCE + 1e-9 if metric == "eps" else revenue_agrees(x, release_value)
        rel = release_value if metric == "eps" else release_value.get("raw")
        if ok and metric == "eps" and q.get("derived"):
            return release_value, "XBRL and the earnings release (the release's figure: a derived fourth quarter drifts by cents)", None
        return (x, "XBRL and the earnings release", None) if ok else (None, "", f"XBRL {x:,.4g} against the release {rel}")
    if q.get("restated") is not None:
        r = q["restated"]
        ok = abs(x - r) <= EPS_TOLERANCE + 1e-9 if metric == "eps" else abs(x - r) <= REVENUE_TOLERANCE * max(abs(x), 1)
        return (x, "XBRL as filed and as restated a year later", None) if ok else (None, "", f"XBRL as filed {x:,.4g}, restated {r:,.4g}")
    return None, "", "one reader only: no readable release and no later filing yet"


def growth_words(metric: str, current: float, prior: float) -> tuple[float | None, str]:
    """Pure: (percent change or None, the phrase). Between a loss and a profit, or from zero, the phrase is in words only."""
    if prior > 0 and current >= 0:
        pct = (current - prior) / prior * 100
        return round(pct, 1), f"{'up' if pct >= 0 else 'down'} {abs(pct):.1f}% from a year earlier"
    if prior < 0 and current > 0:
        return None, "swung to a profit"
    if prior > 0 and current < 0:
        return None, "swung to a loss"
    if prior < 0 and current < 0:
        return None, "loss narrowed" if current > prior else ("loss widened" if current < prior else "loss unchanged")
    if prior == 0:
        return None, "from zero a year earlier"
    return None, "swung to a profit" if current > 0 else "no change"


def hold_for_actions(actions: list[dict], window_start: date, window_end: date) -> str | None:
    """Pure: the reason growth is held, or None: a recorded spin-off, merger, share-exchange acquisition or rename-merge inside the
    comparison window (from the year-ago quarter's first day through the current quarter's last day) means the two quarters
    describe different companies."""
    inside = [a for a in drop_renames_explained(actions) if window_start <= a["date"] <= window_end]
    if not inside:
        return None
    a = max(inside, key=lambda a: a["date"])
    verb = ACTION_VERBS.get(a["kind"], "Had a corporate action ({kind}) on {date}").format(name=a.get("name") or "a business", date=a["date"].isoformat(), kind=a["kind"])
    return f"{verb}, inside the year compared"
