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
    ACTION_VERBS, EPS_FACT_MAX, QUARTER_DAYS, YEAR_DAYS, _current_column, current_column, drop_renames_explained, header_order, split_factor,
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


def filing_growth(us_gaap: dict, sector: str | None, filed_by: date | None = None) -> dict | None:
    """Pure: the latest quarter's revenue against the same quarter a year earlier from the SEC filings alone (Sam, 2026-11-10: the
    walkthrough shows the filing's figure, labelled as the filing's, where the release reads differently): {period_end, value,
    year_ago_end, year_ago_value, growth_pct, phrase, tag, form, filed}, each value as first filed; None when no tag carries the
    quarter and its year-ago quarter. Only quarters filed by `filed_by` count."""
    best = None
    for tag, q in revenue_by_tag(us_gaap, sector):
        ends = sorted(e for e, r in q.items() if filed_by is None or r["as_filed_on"] <= filed_by)
        for end in reversed(ends):
            ya = year_ago(end, q)
            if ya:
                cur, prior = q[end]["as_filed"], q[ya]["as_filed"]
                pct_, phrase = growth_words("revenue", cur, prior)
                row = {"period_end": end, "value": cur, "year_ago_end": ya, "year_ago_value": prior, "growth_pct": pct_, "phrase": phrase,
                       "tag": tag, "form": q[end]["form"], "filed": q[end]["as_filed_on"]}
                if best is None or end > best["period_end"]:
                    best = row
                break
    return best


# ── the release's revenue line ───────────────────────────────────────────────────────────────────────────────────────────────

_REV_LABELS = [r"(?:total\s+)?net\s+sales\s+and\s+operating\s+revenues?", r"total\s+net\s+revenues?", r"total\s+revenues?(?:\s+and\s+other\s+income)?", r"total\s+operating\s+revenues?",
               r"net\s+operating\s+revenues?", r"sales\s+and\s+other\s+operating\s+revenues?", r"railway\s+operating\s+revenues?",
               r"rental\s+and\s+other\s+property\s+revenues?", r"operating\s+revenues?", r"net\s+revenues?", r"total\s+net\s+sales",
               r"net\s+sales", r"revenues?", r"sales"]
# a label that is the company's revenue only when it starts its row: the word before it is not another label word (Nov 10, 2026: AXP's
# "Discount revenue", CPRT's "Service revenues", DRI's "Unearned revenues", REGN's "Collaboration revenue", USB's "Card revenue")
_BARE_LABELS = {r"operating\s+revenues?", r"net\s+revenues?", r"net\s+sales", r"revenues?", r"sales"}
_ROW_OPENERS = {"total", "consolidated", "gaap", "reported", "operations", "income", "earnings", "unaudited", "millions", "thousands",
                "billions", "amounts", "data", "except", "per", "share", "ended", "months", "weeks", "quarter", "dollars", "change", "gaap",
                "statements", "statement",
                # a column heading's last word, before the table's first row (the 385 other stocks' releases, Nov 10, 2026: HCA's
                # "Amount Ratio Revenues", AOS's "% Change YoY Net sales", WDC's "Q/Q Y/Y Revenue", CHTR's "Actual REVENUES", PM's
                # "Currency Net Revenues", CEG's "Non-GAAP Adjustments Operating revenues", CBRE's "Operating Results Revenue")
                "amount", "ratio", "yoy", "y/y", "q/q", "actual", "currency", "adjustments", "results", "forma"}


_LABEL_WORDS = {"revenue", "revenues", "sales"}


def _row_start(before: str) -> bool:
    """Pure: the text before a label leaves it at the start of its row (a figure, a bracket, a heading word ends it), not mid-label."""
    m = re.search(r"([A-Za-z][A-Za-z'’\-/]*)\s*(:?)\s*$", before)
    # a heading ends in a colon ("Revenue: Revenue $ 1,090,579", IDXX) or repeats the label's own word as a column's ("% of Net
    # Revenues Net revenues $ 1,445.9", HAS; "Net Sales Sales Net sales", TSCO)
    return not m or bool(m.group(2)) or m.group(1).lower() in _ROW_OPENERS or m.group(1).lower() in _LABEL_WORDS


_AMOUNT = r"\$?\s?(\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?\d+\.\d+\)?|\(?\d{2,}\)?)"
_SCALE = re.compile(r"\(\s*(?:dollars\s+|\$\s*)?in\s+(millions|thousands|billions)|(?:in|\$)\s+(millions|thousands|billions)\b", re.I)


_PROSE_REV = re.compile(r"(?<![A-Za-z])(?:(reported|total|net|gaap|quarterly|consolidated)\s+)?(?:operating\s+)?(?:net\s+)?revenues?(?:,\s*net\s+of\s+interest\s+expense,)?\s+(?:of|was|were|totaled)\s+"
                        r"\$\s?(\d[\d,]*(?:\.\d+)?)\s+(billion|million)", re.I)
_PROSE_OPENERS = {"quarter", "quarterly", "record", "company", "company's", "firm", "firmwide", "its", "our", "the", "and", "with", "of",
                  "in", "q1", "q2", "q3", "q4", "first-quarter", "second-quarter", "third-quarter", "fourth-quarter", "delivered", "reported",
                  "generated", "achieved", "posted", "on", "worldwide"}
_COMPANY_WORDS = {"total", "consolidated"}       # never "reported": a segment reports too ("Engine Structures reported revenue of $294 million", HWM)
_SEGMENT_BEFORE = re.compile(r"(?:[A-Z][\w&.'-]*\s*)$")


def _prose_revenue(flat: str) -> dict | None:
    """The company-level revenue sentence ("Reported revenue of $49.8 billion", "Revenue of $11.32 billion"): never a segment's
    ("Markets revenue reached ...", "In the CIB, revenue grew"), never guidance or a year's."""
    found = []
    for m in _PROSE_REV.finditer(flat):
        if not m.group(1):
            prev = flat[max(0, m.start() - 30):m.start()]
            if _SEGMENT_BEFORE.search(prev.rstrip()) and not re.search(r"(?:^|[.;:•\n])\s*$", prev):
                continue                         # a capitalised word right before "revenue" names a segment or product
            if re.search(r"(?:increase|decrease|growth|change|rise|decline|gain|drop)\s+in\s*$", prev, re.I):
                continue                         # "an increase in revenue of $27.3 million" (CPRT) is a change, not the quarter's revenue
            w = re.search(r"([A-Za-z][A-Za-z'’\-]*)\s*$", prev)
            if w and w.group(1).lower() not in _PROSE_OPENERS:
                continue                         # "performance revenues of $78.8 million" (ARES), "servicing fee revenue" (STT): a line's
        # its own sentence (GS: "Net revenues were $ 56.24 billion ... for the first nine months of 2026" follows the quarter's sentence)
        left = max(flat.rfind(". ", 0, m.start()), flat.rfind("•", 0, m.start()), 0)
        right = min([i for i in (flat.find(". ", m.end()), flat.find("•", m.end())) if i >= 0] or [len(flat)])
        context = flat[left:right]
        if re.search(r"guidance|outlook|expect|full[- ]year|fiscal[- ]year|year[- ]to[- ]date|twelve months|nine months|six months|for the year|year ended|annual", context, re.I):
            continue
        near = flat[max(0, m.start() - 60):m.start()]
        if re.search(r"\bfiscal\s+(?:year\s+)?(?:20)?\d{2}\b|\bFY\s?'?\d{2}\b|\b20\d{2}\s*$", near, re.I) and not re.search(r"quarter|\bQ[1-4]\b", near, re.I):
            continue                             # "Fiscal 2025 revenue of $37.38 billion" is the year's (MU); "fourth quarter of fiscal 2025" stays
        num = float(m.group(2).replace(",", ""))
        found.append({"raw": m.group(2), "value": num * (1e9 if m.group(3).lower() == "billion" else 1e6), "number": num,
                      "scale": m.group(3).lower() + "s", "how": "revenue sentence", "evidence": flat[max(0, m.start() - 10):m.end() + 10],
                      "company": (m.group(1) or "").lower() in _COMPANY_WORDS or "interest expense" in m.group(0).lower()})
    # the first company-level sentence, one that says so first ("Total revenue", "Revenue, net of interest expense,": BAC's segment
    # bullet "Revenue of $11.6 billion" comes earlier); never the largest (a fourth quarter's release may state the year's revenue in
    # a bullet further down: CVNA's "Revenue totaled $20.322 billion" for 2025)
    return min(found, key=lambda f: 0 if f["company"] else 1) if found else None


# Block 2 (2026-10-20): the release reader took a segment's line for total revenue in 2,045 of 2,182 growth disagreements (Agilent:
# XBRL $1.878 billion against a segment's "revenue of $746 million"). The company's revenue is read from, in order: the consolidated
# statement of income or operations (A, CMCSA); a consolidating statement's last column, the consolidated entity (EXC's ComEd, PECO,
# BGE, PHI, Other, Exelon); a company-level sentence whose own sentence names no year (GS); and any other table whose nearest heading
# names the quarter, never the year (PG's "Fiscal Year ... Net Sales $87.0" before "Fourth Quarter ... Net Sales $21.2").
_STATEMENT = re.compile(r"(?<!table of contents )(?:condensed\s+)?consolidated\s+statements?\s+of\s+(?:income|operations|earnings)\b", re.I)
_CONSOLIDATING = re.compile(r"consolidating\s+statements?\s+of\s+(?:income|operations|earnings)\b", re.I)
STATEMENT_REACH = 2500            # a statement's revenue row sits within this many characters after its heading
_ANNUAL_HEAD = re.compile(r"fiscal\s+year|year\s+ended|twelve\s+months|full[- ]year", re.I)
_QUARTER_HEAD = re.compile(r"quarter|three\s+months|\d{1,2}\s+weeks|\bQ[1-4]\b|\b[1-4]Q\d\d\b", re.I)
_ROW_AMOUNT = re.compile(r"\(?\$?\s?\d[\d,]*(?:\.\d+)?\)?(?!\s*%)(?![\d.,])")


def _annual_heading(before: str) -> bool:
    """Pure: the nearest period heading in the 400 characters before a row names a year, not a quarter."""
    w = before[-400:]
    a = [m.end() for m in _ANNUAL_HEAD.finditer(w)]
    q = [m.end() for m in _QUARTER_HEAD.finditer(w)]
    return bool(a) and (not q or max(a) > max(q))


def _row_amounts(flat: str, at: int) -> list[str]:
    run = re.split(r"[A-Za-z]{2,}", flat[at:at + 300], maxsplit=1)[0]
    return [m.group(0).strip() for m in _ROW_AMOUNT.finditer(run) if re.search(r"\d", m.group(0))]


def _table_revenue(flat: str, lo: int, hi: int, how_suffix: str = "", last_column: bool = False, skip_annual: bool = True) -> dict | None:
    """Pure: the first revenue row between lo and hi (labels in _REV_LABELS' order of preference), its current column."""
    region = flat[lo:hi]
    for label in _REV_LABELS:
        pat = re.compile(rf"(?<![A-Za-z])(?<!of\s)(?<!cost\sof\s)({label})(?:\s*\(\w\))?[:\s]+{_AMOUNT}(?!\s*%)\s+{_AMOUNT}(?!\s*%)", re.I)
        for m in pat.finditer(region):
            at = lo + m.start()
            before = flat[max(0, at - 40):at].lower()
            if re.search(r"cost\s+of\s*$|of\s*$|growth\s*$|per\s*$|percentage\s+of\s+total\s*$", before) or re.search(r"guidance|outlook", flat[max(0, at - 200):at], re.I):
                continue
            if skip_annual and _annual_heading(flat[:at]):
                continue
            if label in _BARE_LABELS and not _row_start(flat[max(0, at - 40):at]):
                continue                         # "Discount revenue", "Service revenues", "Deferred revenue": a line, never the total
            amounts = _row_amounts(flat, lo + m.start(2))
            if last_column and amounts:
                raw = amounts[-1]
            else:
                idx = current_column(flat[:at], len(amounts))
                raw = amounts[idx] if idx is not None and idx < len(amounts) else (m.group(3) if header_order(flat, at) == "prior-first" else m.group(2))
            raw = raw.replace("$", "").strip()
            scale_m = None
            for sm in _SCALE.finditer(flat[:at]):
                scale_m = sm
            unit = (scale_m.group(1) or scale_m.group(2)).lower() if scale_m else None
            factor = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}.get(unit, None)
            num = float(raw.replace(",", "").strip("()"))
            return {"raw": raw, "value": num * factor if factor else None, "number": num, "scale": unit, "how": m.group(1).lower() + how_suffix,
                    "evidence": flat[max(0, at - 10):lo + m.end() + 10]}
    return None


def parse_release_revenue(text: str) -> dict | None:
    """Pure: the quarter's company-level revenue from an earnings release, from (in order) the consolidated statement of income or
    operations, a consolidating statement's consolidated (last) column, a company-level revenue sentence, or another table whose
    heading names the quarter. Never a cost line ("cost of revenues"), a percentage, a segment's or subsidiary's line, or the year's.
    The current column per the heading before the row (valuation.current_column, then header_order). Returns {value (in dollars when
    the table states its unit), raw, scale, how, evidence} or None."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    for st in _STATEMENT.finditer(flat):
        hit = _table_revenue(flat, st.end(), min(len(flat), st.end() + STATEMENT_REACH), ", consolidated statement", skip_annual=False)
        if hit:
            return hit
    for st in _CONSOLIDATING.finditer(flat):
        hit = _table_revenue(flat, st.end(), min(len(flat), st.end() + STATEMENT_REACH), ", consolidating statement, consolidated column", last_column=True, skip_annual=False)
        if hit:
            return hit
    prose = _prose_revenue(flat)
    if prose:
        return prose
    return _table_revenue(flat, 0, len(flat))


def revenue_agrees(xbrl: float, release: dict) -> bool:
    """Pure: the release's figure is the XBRL figure at the release's precision, in the unit the table states or, when that does not
    match, in whichever of dollars, thousands, millions or billions does."""
    raw = release["raw"].strip("()$ ")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    # the stated unit first, then every other: a heading's last unit can be another column's (AAPL, 2026-11-10: "(In millions, except
    # number of shares, which are reflected in thousands ...)" read as thousands), and a figure equal to the last digit in some unit is
    # the same figure; a different one never lines up digit for digit
    stated = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}.get(release.get("scale"))
    for factor in ([stated] if stated else []) + [f for f in (1, 1e3, 1e6, 1e9) if f != stated]:
        if abs(release["number"] * factor - xbrl) <= factor * 10 ** -decimals + 1:      # one unit of the release's last digit (BSX 5,286 against XBRL $5.2854B, rounded differently)
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


def no_longer_confirmed(stored: list[tuple[str, date]], rows: list[dict], unread: list[str]) -> list[tuple[str, date]]:
    """Pure: the stored figures [(metric, period_end)] a run no longer confirms, which are removed (Sam, 2026-11-10). A figure goes
    only when the reader read every source (`unread` is empty) and the quarter is one it read (on or after the oldest quarter in
    `rows`) yet came out without both of its values agreed, or is no longer a quarter the filings yield. Nothing is removed when a
    read failed (the stored figure stands until a run that reads everything), and a quarter older than those read is left alone:
    the reader did not look at it."""
    if unread or not rows:
        return []
    confirmed = {(r["metric"], r["period_end"]) for r in rows if r["value"] is not None and r["year_ago_value"] is not None}
    floor = min(r["period_end"] for r in rows)
    return sorted((m, e) for m, e in stored if e >= floor and (m, e) not in confirmed)


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
