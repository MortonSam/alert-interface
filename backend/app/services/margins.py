"""How much of each sales dollar a company keeps, now and three years earlier (Ivy's walkthrough, step 3), from SEC company facts.

The measure depends on the sector, and its plain label says which it is:
    gross      sales less the cost of what was sold, only when the company itself files GrossProfit (a cost-of-goods tag can cover
               part of the costs: UnitedHealth's covers pharmacy goods, not medical costs, and would read as an 89% gross margin)
    operating  profit from operations, for a company that reports no gross profit
               (and the net margin below for one that files neither recently)
    net        profit after every cost, for banks, insurers and other financials, which have no cost of goods
Real estate trusts get no measure: depreciation makes their margins say little, and the funds-from-operations figure they are
judged by is not in XBRL. A real estate company that is not a trust (CBRE, CoStar: "Real Estate Services") is read like any other
company (is_trust). "Now" is the latest four consecutive quarters as first filed; "three years earlier" is the four
quarters ending THREE_YEARS_DAYS before (within END_MATCH_DAYS). Every figure is checked against MARGIN_BAND before it is used.

Revenue is the company's total, on one series per half: `Revenues` when it is filed beside a contract-revenue tag for the same
quarters and is larger (URI's contract revenue leaves out its rentals), and two tags joined into one series when the company
changed tags and both state the same figure for every recent quarter they share (joined). Where four straight quarters are
not in the facts, the same four quarters are read as the fiscal year before them, plus the year to date, less the same stretch a
year earlier (year_and_part: CAH, KR, FDX).

by_measure carries every measure the company's filings support ({measure: {now, then, now_end, then_end}}), the step's own among
them, so Compare can show two companies on a measure both have (walkthrough.compare_table). A financial is read on net only.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.growth import quarter_readings, revenue_tags

MARGINS_VERSION = 6                  # 2 (2026-10-19): the profit line with a recent quarter; three years earlier on any revenue tag
                                     # 3 (same day): every measure the company files (by_measure), so Compare can set like against like
                                     # 4 (2026-11-10): a company that files neither gross profit nor operating income recently is read on
                                     #   its profit margin (56 stocks showed no margin; 39 of them file only net income)
                                     # 5 (same day, Sam): a real estate company that is not a trust (CBRE, CSGP) gets a margin
                                     # 6 (2026-11-11, Sam's item 6): total revenue over a part of it (URI read 167.7% on contract
                                     #   revenue alone), a changed revenue tag joined (CMI, FISV), the year plus the year to date
                                     #   where four straight quarters are not in the facts (CAH, KR, FDX), and the facts of the
                                     #   registrant before (XOM, through build_walkthroughs)
THREE_YEARS_DAYS = 1092              # 156 weeks: the fiscal quarter three years earlier (52/53-week years drift a few days)
END_MATCH_DAYS = 20
FRESH_DAYS = 230                     # the latest quarter used ended within this many days (a tag the company stopped filing is skipped)
QUARTER_GAP_DAYS = (80, 100)
YEAR_DAYS = (350, 380)               # a fiscal year
STRETCH_MATCH_DAYS = 8               # the year to date and the same stretch a year earlier differ by at most this (a 53-week year)
JOIN_LOOKBACK_DAYS = 800             # two revenue tags are one series when they agree on every quarter both carry this close to the end read
JOIN_MIN_SHARED = 2
JOIN_TOLERANCE = 0.001
WHOLE_REVENUE_TAG = "Revenues"
PART_REVENUE_TAGS = {"RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax"}
YEAR_BASIS = "the fiscal year"       # how a reading without four straight quarters was made (kept with the reading, never shown)
YEAR_AND_PART_BASIS = "the fiscal year plus the year to date, less the same stretch a year earlier"
MARGIN_BAND = {"gross": (-100.0, 100.0), "operating": (-300.0, 100.0), "net": (-300.0, 100.0)}

GROSS_TAGS = ["GrossProfit"]
OPERATING_TAGS = ["OperatingIncomeLoss"]
NET_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]

MEASURE_LABEL = {"gross": "gross margin", "operating": "operating margin", "net": "profit margin"}
MEASURE_PLAIN = {"gross": "after paying for what it sold", "operating": "as operating profit", "net": "as profit after every cost"}
NO_MEASURE = {"Real Estate": "Real estate trusts are judged by funds from operations, which their filings do not tag, so Ivy shows no margin for them"}


def is_trust(sector: str | None, industry: str | None) -> bool:
    """Pure: GICS Real Estate with a REIT sub-industry ("Retail REITs"). Real estate services (CBRE, CoStar) are not trusts: they
    keep the P/E and get a margin."""
    return (sector or "") in NO_MEASURE and "REIT" in (industry or "")


def measure_for(sector: str | None, industry: str | None) -> str | None:
    """Pure: the first measure tried for a company ("gross" falls back to "operating" when no cost of revenue is filed); None for a
    real estate trust."""
    if is_trust(sector, industry):
        return None
    return "net" if sector == "Financials" else "gross"


def _quarters(us_gaap: dict, tag: str) -> dict[date, dict]:
    entries = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
    return quarter_readings(entries, per_share=False) if entries else {}


def four_ending(quarters: dict[date, dict], end: date) -> list[date] | None:
    """Pure: the four consecutive quarter ends finishing at `end`, or None when one is missing."""
    ends = sorted(d for d in quarters if d <= end)
    if not ends or ends[-1] != end or len(ends) < 4:
        return None
    four = ends[-4:]
    if any(not QUARTER_GAP_DAYS[0] <= (b - a).days <= QUARTER_GAP_DAYS[1] for a, b in zip(four, four[1:])):
        return None
    return four


def ttm(quarters: dict[date, dict], four: list[date]) -> float:
    return sum(quarters[d]["as_filed"] for d in four)


def _profit_candidates(us_gaap: dict, measure: str) -> list[tuple[str, dict[date, dict], str]]:
    """[(the measure, {end: reading} of the profit line, its tag)] in the order tried: net income for "net"; gross profit, then
    operating income, otherwise. The caller keeps the first that carries a recent quarter (a company that filed GrossProfit
    until 2009 or 2020, AMZN and CAT, is read on operating income now)."""
    tags = [("net", t) for t in NET_TAGS] if measure == "net" else (
        [("gross", t) for t in GROSS_TAGS] + [("operating", t) for t in OPERATING_TAGS]
        + [("net", t) for t in NET_TAGS])       # neither filed recently (XOM, LLY, MRK, PFE): the profit margin, labelled as such (2026-11-10)
    return [(m, q, t) for m, t in tags if (q := _quarters(us_gaap, t))]


def joined(a: dict[date, dict], b: dict[date, dict], near: date) -> dict[date, dict] | None:
    """Pure: two revenue tags as one series (a's reading where both carry a quarter), or None unless each carries a quarter the
    other lacks and they state the same figure for every quarter both carry within JOIN_LOOKBACK_DAYS of `near`, at least
    JOIN_MIN_SHARED of them. A company that changes its revenue tag files the newer quarters, and their year-ago columns, under
    the new one (CMI, FISV in 2026), so the quarter between is under the old tag alone."""
    shared = [d for d in a if d in b and abs((near - d).days) <= JOIN_LOOKBACK_DAYS]
    if len(shared) < JOIN_MIN_SHARED or not (set(a) - set(b) and set(b) - set(a)):
        return None
    if any(abs(a[d]["as_filed"] - b[d]["as_filed"]) > JOIN_TOLERANCE * abs(a[d]["as_filed"]) for d in shared):
        return None
    return {**b, **a}


def _revenue_series(us_gaap: dict, sector: str | None, near: date) -> list[tuple[str, dict[date, dict]]]:
    """[(tag, {end: reading})] in the order tried: each revenue tag in the sector's order, then each pair that joins."""
    single = [(t, q) for t in revenue_tags(sector) if (q := _quarters(us_gaap, t))]
    pairs = [(f"{ta} and {tb}", j) for i, (ta, qa) in enumerate(single) for tb, qb in single[i + 1:] if (j := joined(qa, qb, near))]
    return single + pairs


def _ttm_ending(us_gaap: dict, sector: str | None, profit: dict[date, dict], target: date) -> tuple[date, list[date], str, dict] | None:
    """(end, its four quarters, the revenue tag, its readings) for four quarters ending within END_MATCH_DAYS of target, on the
    first revenue series in the sector's order that carries them with the profit line; `Revenues` instead of a contract-revenue
    tag when it carries the same four quarters and is larger (the whole, never a part)."""
    series = _revenue_series(us_gaap, sector, target)
    for rtag, revenue in series:
        common = {d: revenue[d] for d in revenue if d in profit}
        end = min((d for d in common if abs((d - target).days) <= END_MATCH_DAYS), key=lambda d: abs((d - target).days), default=None)
        four = four_ending(common, end) if end else None
        if four and ttm(revenue, four) > 0:
            whole = dict(series).get(WHOLE_REVENUE_TAG, {})
            if rtag in PART_REVENUE_TAGS and all(d in whole for d in four) and ttm(whole, four) > ttm(revenue, four):
                return end, four, WHOLE_REVENUE_TAG, whole
            return end, four, rtag, revenue
    return None


def _periods(us_gaap: dict, tag: str) -> dict[tuple[date, date], list[dict]]:
    """{(start, end): [{val, filed, accn}] earliest filing first} for one tag's dollar facts."""
    out: dict[tuple[date, date], list[dict]] = {}
    for e in us_gaap.get(tag, {}).get("units", {}).get("USD", []):
        try:
            start, end, filed = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), date.fromisoformat(e["filed"])
        except (KeyError, TypeError, ValueError):
            continue
        if e.get("val") is not None:
            out.setdefault((start, end), []).append({"val": float(e["val"]), "filed": filed, "accn": e.get("accn")})
    for rows in out.values():
        rows.sort(key=lambda r: r["filed"])
    return out


def _stretches(periods: dict, end: date) -> list[tuple[tuple[date, date], tuple[date, date] | None, tuple[date, date] | None]]:
    """[(the year to date ending `end`, the fiscal year before it, the same stretch of that year)]: the three periods that make
    the four quarters ending `end`. A fiscal year ending on `end` stands alone."""
    out = []
    for s, e in periods:
        if e != end:
            continue
        if YEAR_DAYS[0] <= (e - s).days <= YEAR_DAYS[1]:
            out.append(((s, e), None, None))
            continue
        for a0, a1 in periods:
            if a1 != s - timedelta(days=1) or not YEAR_DAYS[0] <= (a1 - a0).days <= YEAR_DAYS[1]:
                continue
            for p0, p1 in periods:
                if p0 == a0 and p1 < a1 and abs((p1 - p0).days - (e - s).days) <= STRETCH_MATCH_DAYS:
                    out.append(((s, e), (a0, a1), (p0, p1)))
    return out


def year_and_part(profit: dict, revenue: dict, end: date) -> dict | None:
    """Pure: {start, end, profit, revenue, filed, basis} for the four quarters ending `end`, read as the fiscal year before them, plus
    the year to date, less the same stretch a year earlier, each as first filed (the earlier stretch as the filing that
    carries the year to date restates it, when it does). For a company whose facts lack four straight quarters: a 10-Q the
    SEC's facts leave out (CAH's of April 2026), a 16-week first quarter (KR), a changed fiscal year (FDX)."""
    for now, year, before in _stretches(profit, end):
        if any(k is not None and k not in revenue for k in (now, year, before)):
            continue
        total, filed = {}, []
        for name, periods in (("profit", profit), ("revenue", revenue)):
            first = periods[now][0]
            if year is None:
                total[name] = first["val"]
                filed.append(first["filed"])
                continue
            same = next((r for r in periods[before] if r["accn"] and r["accn"] == first["accn"]), periods[before][0])
            total[name] = periods[year][0]["val"] + first["val"] - same["val"]
            filed += [first["filed"], periods[year][0]["filed"]]
        if total["revenue"] > 0:
            return {"start": now[0] if year is None else before[1] + timedelta(days=1), "end": end, "profit": total["profit"],
                    "revenue": total["revenue"], "filed": max(filed), "basis": YEAR_BASIS if year is None else YEAR_AND_PART_BASIS}
    return None


def _year_ending(us_gaap: dict, sector: str | None, ptag: str, target: date) -> tuple[dict, str] | None:
    """(year_and_part's reading, the revenue tag) for the period end nearest `target` within END_MATCH_DAYS, on the first
    revenue tag that carries the same periods as the profit line (`Revenues` over a contract-revenue tag when larger)."""
    profit = _periods(us_gaap, ptag)
    ends = sorted({e for _, e in profit if abs((e - target).days) <= END_MATCH_DAYS}, key=lambda d: abs((d - target).days))
    tags = [(t, p) for t in revenue_tags(sector) if (p := _periods(us_gaap, t))]
    for end in ends:
        for rtag, revenue in tags:
            got = year_and_part(profit, revenue, end)
            if not got:
                continue
            whole = year_and_part(profit, dict(tags).get(WHOLE_REVENUE_TAG, {}), end) if rtag in PART_REVENUE_TAGS else None
            if whole and whole["start"] == got["start"] and whole["revenue"] > got["revenue"]:
                return whole, WHOLE_REVENUE_TAG
            return got, rtag
    return None


MEASURE_TAGS = {"gross": GROSS_TAGS, "operating": OPERATING_TAGS, "net": NET_TAGS}


def by_measure(facts: dict, sector: str | None, today: date, industry: str | None = None) -> dict[str, dict]:
    """Pure: {measure: {now, then, now_end, then_end}} for each measure the filings support within its band (net only for a financial)."""
    if measure_for(sector, industry) is None:
        return {}
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out = {}
    for measure in (("net",) if measure_for(sector, industry) == "net" else ("gross", "operating", "net")):
        cands = [(measure, q, t) for t in MEASURE_TAGS[measure] if (q := _quarters(us_gaap, t))]
        r = _read(us_gaap, sector, cands, today)
        if r.get("ok"):
            out[measure] = {"now": r["now"], "then": r["then"], "now_end": r["now_end"], "then_end": r["then_end"]}
    return out


def margins(facts: dict, sector: str | None, today: date, industry: str | None = None) -> dict:
    """Pure: {ok, measure, label, plain, now, then, now_start, now_end, then_end, filed_on, revenue_tag, profit_tag, now_revenue, now_profit,
    then_revenue, then_profit} or {ok: False, reason}. Percentages to one decimal. "Now" is the latest four consecutive quarters
    ending within FRESH_DAYS; "three years earlier" may read another revenue tag (a company that changed its revenue tag), never
    another profit line."""
    first = measure_for(sector, industry)
    if first is None:
        return {"ok": False, "reason": NO_MEASURE[sector]}
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out = _read(us_gaap, sector, _profit_candidates(us_gaap, first), today)
    if out.get("ok"):
        out["by_measure"] = by_measure(facts, sector, today, industry)
    return out


def _in_band(measure: str, now: float, then: float | None) -> str | None:
    lo, hi = MARGIN_BAND[measure]
    for w, v in (("for the last four quarters", now), ("three years earlier", then)):
        if v is not None and not lo <= v <= hi:
            return f"the {MEASURE_LABEL[measure]} {w} came out at {v}%, outside the {lo:.0f}% to {hi:.0f}% band, so it is held"
    return None


def _then(us_gaap: dict, sector: str | None, profit: dict[date, dict], ptag: str, end: date) -> dict:
    """{then, then_end, then_revenue_tag, then_revenue, then_profit} for the four quarters three years before `end`: by quarters,
    or by year_and_part where the quarters are not there; every value None when neither reads."""
    target = end - timedelta(days=THREE_YEARS_DAYS)
    got = _ttm_ending(us_gaap, sector, profit, target)
    if got:
        then_end, four, rtag, revenue = got
        r, pr = ttm(revenue, four), ttm(profit, four)
    elif (y := _year_ending(us_gaap, sector, ptag, target)):
        then_end, rtag, r, pr = y[0]["end"], y[1], y[0]["revenue"], y[0]["profit"]
    else:
        return {"then": None, "then_end": None, "then_revenue_tag": None, "then_revenue": None, "then_profit": None}
    return {"then": round(pr / r * 100, 1), "then_end": then_end, "then_revenue_tag": rtag, "then_revenue": r, "then_profit": pr}


def _now_quarters(us_gaap: dict, sector: str | None, profit: dict[date, dict], end: date) -> dict | None:
    got = _ttm_ending(us_gaap, sector, profit, end)
    if not got or got[0] != end:
        return None
    _, four, rtag, revenue = got
    return {"now_start": four[0], "now_revenue": ttm(revenue, four), "now_profit": ttm(profit, four), "revenue_tag": rtag,
            "filed_on": max(max(revenue[d]["as_filed_on"] for d in four), max(profit[d]["as_filed_on"] for d in four))}


def _now_year(us_gaap: dict, sector: str | None, ptag: str, end: date) -> dict | None:
    y = _year_ending(us_gaap, sector, ptag, end)
    if not y or y[0]["end"] != end:
        return None
    return {"now_start": y[0]["start"], "now_revenue": y[0]["revenue"], "now_profit": y[0]["profit"], "revenue_tag": y[1], "filed_on": y[0]["filed"],
            "basis": y[0]["basis"]}


def _read(us_gaap: dict, sector: str | None, candidates: list, today: date) -> dict:
    """The first measure that reads, at its latest period end within FRESH_DAYS that reads: on the first of its profit tags that
    carries four straight quarters to that end, or, where none does, the first that reads by year_and_part. So a later end is
    never passed over for an older one (CME's first tag stops two quarters back), nor quarters as filed for arithmetic."""
    for measure in dict.fromkeys(m for m, _, _ in candidates):
        lines = [(profit, ptag) for m, profit, ptag in candidates if m == measure]
        ends = {d for profit, _ in lines for d in profit} | {e for _, ptag in lines for s, e in _periods(us_gaap, ptag) if (e - s).days <= YEAR_DAYS[1]}
        for end in sorted((d for d in ends if 0 <= (today - d).days <= FRESH_DAYS), reverse=True):
            read = next(((n, profit, ptag) for profit, ptag in lines if (n := _now_quarters(us_gaap, sector, profit, end))), None) \
                or next(((n, profit, ptag) for profit, ptag in lines if (n := _now_year(us_gaap, sector, ptag, end))), None)
            if not read:
                continue
            now, profit, ptag = read
            then = _then(us_gaap, sector, profit, ptag, end)
            pct = round(now["now_profit"] / now["now_revenue"] * 100, 1)
            held = _in_band(measure, pct, then["then"])
            if held:
                return {"ok": False, "reason": held}
            return {"ok": True, "measure": measure, "label": MEASURE_LABEL[measure], "plain": MEASURE_PLAIN[measure], "now": pct, "now_end": end,
                    "profit_tag": ptag, **now, **then}
    return {"ok": False, "reason": "its filings do not tag four straight recent quarters of revenue and profit"}
