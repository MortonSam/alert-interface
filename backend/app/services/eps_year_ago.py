"""Reported EPS against the same quarter a year earlier, from SEC filings (eps_quarters: GAAP diluted EPS per quarter as parsed
from XBRL by compute_pe, the fourth quarter derived from the 10-K). No analyst estimate is involved.

    year_ago_pairs(quarters)            -> each quarter with its year-ago quarter, the change and its phrase (growth.growth_words)
    quarter_for_report(quarters, day)   -> the quarter a report on `day` announced: the latest one ended 1 to 120 days before it
    load_quarters(db, symbol)           -> [(period_end, eps)] ascending, one per period end
    eps_line(pair)                      -> "EPS $2.22, up 111.4% from $1.05 a year ago", or the plain absence

A quarter's year-ago quarter ended YEAR_AGO_DAYS before it. Between a loss and a profit the change is in words only.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.services.growth import YEAR_AGO_DAYS, growth_words

REPORT_LAG_DAYS = (1, 120)      # a report announces the quarter that ended this many days before it
NO_YEAR_AGO = "No EPS figure from the same quarter a year earlier is on file."


def _money(x: float) -> str:
    return f"-${abs(x):.2f}" if x < 0 else f"${x:.2f}"


def year_ago_pairs(quarters: list[tuple[date, float]]) -> list[dict]:
    """Pure: {period_end, eps, year_ago_end, year_ago_eps, pct, phrase} per quarter, newest first; the year-ago fields are None
    when no quarter ended YEAR_AGO_DAYS earlier."""
    q = sorted(quarters)
    out = []
    for end, eps in reversed(q):
        ya = next(((e, v) for e, v in q if YEAR_AGO_DAYS[0] <= (end - e).days <= YEAR_AGO_DAYS[1]), None)
        pct, phrase = growth_words("eps", float(eps), float(ya[1])) if ya else (None, None)
        out.append({"period_end": end, "eps": float(eps), "year_ago_end": ya[0] if ya else None,
                    "year_ago_eps": float(ya[1]) if ya else None, "pct": pct, "phrase": phrase})
    return out


def quarter_for_report(pairs: list[dict], report_day: date) -> dict | None:
    """Pure: the pair for the quarter a report on `report_day` announced."""
    cands = [p for p in pairs if REPORT_LAG_DAYS[0] <= (report_day - p["period_end"]).days <= REPORT_LAG_DAYS[1]]
    return max(cands, key=lambda p: p["period_end"]) if cands else None


def eps_line(pair: dict | None) -> str | None:
    """Pure: the reported EPS against a year earlier, e.g. "EPS $2.22, up 111.4% from $1.05 a year ago", or "EPS $0.29, unchanged
    from $0.29 a year ago" when the change rounds to 0.0%; with no year-ago
    quarter, the EPS and the plain absence; None with no EPS at all."""
    if pair is None:
        return None
    m = pair.get("measure") or "EPS"            # "FFO per share" for a REIT (services/ffo)
    if pair["year_ago_eps"] is None:
        return f"{m} {_money(pair['eps'])}. " + (NO_YEAR_AGO if m == "EPS" else NO_YEAR_AGO.replace("No EPS figure", f"No {m.split(' per ')[0]} figure"))
    if pair["pct"] is not None:
        if f"{abs(pair['pct']):.1f}" == "0.0":      # rounds to 0.0%: never "up 0.0%"
            return f"{m} {_money(pair['eps'])}, unchanged from {_money(pair['year_ago_eps'])} a year ago"
        direction = "up" if pair["pct"] >= 0 else "down"
        return f"{m} {_money(pair['eps'])}, {direction} {abs(pair['pct']):.1f}% from {_money(pair['year_ago_eps'])} a year ago"
    return f"{m} {_money(pair['eps'])} against {_money(pair['year_ago_eps'])} a year ago, {pair['phrase']}"


async def load_quarters(db, symbol: str) -> list[tuple[date, float]]:
    rows = (await db.execute(text("""SELECT DISTINCT ON (period_end) period_end, eps FROM eps_quarters WHERE symbol = :s AND eps IS NOT NULL
        ORDER BY period_end, filed_on DESC NULLS LAST"""), {"s": symbol})).all()
    return [(r.period_end, float(r.eps)) for r in rows]
