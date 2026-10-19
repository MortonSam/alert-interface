"""How much of each sales dollar a company keeps, now and three years earlier (Ivy's walkthrough, step 3), from SEC company facts.

The measure depends on the sector, and its plain label says which it is:
    gross      sales less the cost of what was sold, only when the company itself files GrossProfit (a cost-of-goods tag can cover
               part of the costs: UnitedHealth's covers pharmacy goods, not medical costs, and would read as an 89% gross margin)
    operating  profit from operations, for a company that reports no gross profit
    net        profit after every cost, for banks, insurers and other financials, which have no cost of goods
Real estate trusts get no measure: depreciation makes their margins say little, and the funds-from-operations figure they are
judged by is not in XBRL. "Now" is the latest four consecutive quarters as first filed; "three years earlier" is the four
quarters ending THREE_YEARS_DAYS before (within END_MATCH_DAYS). Both halves use one revenue tag. Every figure is checked
against MARGIN_BAND before it is used.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.growth import quarter_readings, revenue_tags

MARGINS_VERSION = 2                  # 2 (2026-10-19): the profit line with a recent quarter; three years earlier on any revenue tag
THREE_YEARS_DAYS = 1092              # 156 weeks: the fiscal quarter three years earlier (52/53-week years drift a few days)
END_MATCH_DAYS = 20
FRESH_DAYS = 230                     # the latest quarter used ended within this many days (a tag the company stopped filing is skipped)
QUARTER_GAP_DAYS = (80, 100)
MARGIN_BAND = {"gross": (-100.0, 100.0), "operating": (-300.0, 100.0), "net": (-300.0, 100.0)}

GROSS_TAGS = ["GrossProfit"]
OPERATING_TAGS = ["OperatingIncomeLoss"]
NET_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]

MEASURE_LABEL = {"gross": "gross margin", "operating": "operating margin", "net": "profit margin"}
MEASURE_PLAIN = {"gross": "after paying for what it sold", "operating": "as operating profit", "net": "as profit after every cost"}
NO_MEASURE = {"Real Estate": "Real estate trusts are judged by funds from operations, which their filings do not tag, so Ivy shows no margin for them"}


def measure_for(sector: str | None) -> str | None:
    """Pure: the first measure tried for a sector ("gross" falls back to "operating" when no cost of revenue is filed)."""
    if sector in NO_MEASURE:
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
    tags = [("net", t) for t in NET_TAGS] if measure == "net" else [("gross", t) for t in GROSS_TAGS] + [("operating", t) for t in OPERATING_TAGS]
    return [(m, q, t) for m, t in tags if (q := _quarters(us_gaap, t))]


def _ttm_ending(us_gaap: dict, sector: str | None, profit: dict[date, dict], target: date) -> tuple[date, list[date], str, dict] | None:
    """(end, its four quarters, the revenue tag, its readings) for four quarters ending within END_MATCH_DAYS of target, on the
    first revenue tag in the sector's order that carries them with the profit line."""
    for rtag in revenue_tags(sector):
        revenue = _quarters(us_gaap, rtag)
        common = {d: revenue[d] for d in revenue if d in profit}
        end = min((d for d in common if abs((d - target).days) <= END_MATCH_DAYS), key=lambda d: abs((d - target).days), default=None)
        four = four_ending(common, end) if end else None
        if four and ttm(revenue, four) > 0:
            return end, four, rtag, revenue
    return None


def margins(facts: dict, sector: str | None, today: date) -> dict:
    """Pure: {ok, measure, label, plain, now, then, now_start, now_end, then_end, filed_on, revenue_tag, profit_tag, now_revenue, now_profit,
    then_revenue, then_profit} or {ok: False, reason}. Percentages to one decimal. "Now" is the latest four consecutive quarters
    ending within FRESH_DAYS; "three years earlier" may read another revenue tag (a company that changed its revenue tag), never
    another profit line."""
    first = measure_for(sector)
    if first is None:
        return {"ok": False, "reason": NO_MEASURE[sector]}
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for measure, profit, ptag in _profit_candidates(us_gaap, first):
        recent = [d for d in profit if (today - d).days <= FRESH_DAYS]
        for end in sorted(recent, reverse=True)[:2]:
            got = _ttm_ending(us_gaap, sector, profit, end)
            if not got or got[0] != end:
                continue
            end, four_now, rtag, revenue = got
            r_now, p_now = ttm(revenue, four_now), ttm(profit, four_now)
            now = round(p_now / r_now * 100, 1)
            then_got = _ttm_ending(us_gaap, sector, profit, end - timedelta(days=THREE_YEARS_DAYS))
            then = r_then = p_then = then_end = then_tag = None
            if then_got:
                then_end, four_then, then_tag, rev_then = then_got
                r_then, p_then = ttm(rev_then, four_then), ttm(profit, four_then)
                then = round(p_then / r_then * 100, 1)
            lo, hi = MARGIN_BAND[measure]
            out_of_band = [(w, v) for w, v in (("for the last four quarters", now), ("three years earlier", then)) if v is not None and not lo <= v <= hi]
            if out_of_band:
                w, v = out_of_band[0]
                return {"ok": False, "reason": f"the {MEASURE_LABEL[measure]} {w} came out at {v}%, outside the {lo:.0f}% to {hi:.0f}% band, so it is held"}
            filed_on = max(max(revenue[d]["as_filed_on"] for d in four_now), max(profit[d]["as_filed_on"] for d in four_now))
            return {"ok": True, "measure": measure, "label": MEASURE_LABEL[measure], "plain": MEASURE_PLAIN[measure], "now": now, "then": then,
                    "now_start": four_now[0], "now_end": end, "then_end": then_end, "filed_on": filed_on, "revenue_tag": rtag, "then_revenue_tag": then_tag,
                    "profit_tag": ptag, "now_revenue": r_now, "now_profit": p_now, "then_revenue": r_then, "then_profit": p_then}
    return {"ok": False, "reason": "its filings do not tag four straight recent quarters of sales and profit"}
