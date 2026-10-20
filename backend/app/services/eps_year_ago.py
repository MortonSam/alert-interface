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

# a report announces the quarter that ended this many days before it. 95, not 120 (2026-10-20): with the new quarter not on file yet,
# 120 days reached back to the previous quarter, so JPM's Oct 13 report showed Q2's $7.70 (Jun 30, 105 days earlier) and PLD's Oct 15
# report Q2's FFO $1.70; a quarterly report comes well inside 95 days of its quarter's end, the next quarter's end never
REPORT_LAG_DAYS = (1, 95)
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
    fig = f"{m} {_money(pair['eps'])}{pair.get('note') or ''}"     # a derived FFO figure says so (services/ffo.DERIVED_NOTE)
    if pair["year_ago_eps"] is None:
        return f"{fig}. " + (NO_YEAR_AGO if m == "EPS" else NO_YEAR_AGO.replace("No EPS figure", f"No {m.split(' per ')[0]} figure"))
    if pair["pct"] is not None:
        if f"{abs(pair['pct']):.1f}" == "0.0":      # rounds to 0.0%: never "up 0.0%"
            return f"{fig}, unchanged from {_money(pair['year_ago_eps'])} a year ago"
        direction = "up" if pair["pct"] >= 0 else "down"
        return f"{fig}, {direction} {abs(pair['pct']):.1f}% from {_money(pair['year_ago_eps'])} a year ago"
    return f"{fig} against {_money(pair['year_ago_eps'])} a year ago, {pair['phrase']}"


async def load_quarters(db, symbol: str) -> list[tuple[date, float]]:
    """GAAP diluted EPS per quarter from XBRL (eps_quarters), and for a quarter XBRL does not hold yet, the figure read from its earnings
    release where both readers agreed (release_eps, diluted basis, with the quarter's end): XBRL lags a report by weeks (JPM's Q3 2026,
    reported Oct 13, is $5.57 in its release and not yet in XBRL)."""
    rows = (await db.execute(text("""SELECT DISTINCT ON (period_end) period_end, eps FROM eps_quarters WHERE symbol = :s AND eps IS NOT NULL
        ORDER BY period_end, filed_on DESC NULLS LAST"""), {"s": symbol})).all()
    out = {r.period_end: float(r.eps) for r in rows}
    rel = (await db.execute(text("""SELECT DISTINCT ON (period_end) period_end, diluted_eps_gaap FROM release_eps WHERE symbol = :s
        AND eps_basis = 'diluted' AND diluted_eps_gaap IS NOT NULL AND period_end IS NOT NULL ORDER BY period_end, report_date DESC"""), {"s": symbol})).all()
    for r in rel:
        out.setdefault(r.period_end, float(r.diluted_eps_gaap))
    return sorted(out.items())
