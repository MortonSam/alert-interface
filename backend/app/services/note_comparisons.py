"""The comparisons a research note may draw, computed here from stored, dated sources and handed to both the writer and the
verifier, so every point that states a figure can set it against something:

  - the company's own reported EPS against the same quarter a year earlier, for its last four quarters, and its trailing four
    quarters against the four before (eps_quarters, from SEC filings, services/eps_year_ago)
  - sector peers: the median change in EPS against a year earlier across the active tickers in its GICS sector whose latest quarter
    ended within PEER_WINDOW_DAYS of its own
  - revenue against a year earlier where two readers agree (growth_figures)
  - margins and growth for the trailing twelve months against the five-year average (the financials the note page shows)

Nothing about the beat rate or the stock's moves after past reports: the ticker page shows those.
"""
from __future__ import annotations

from datetime import date
from statistics import median

from sqlalchemy import text

from app.services.eps_year_ago import load_quarters, year_ago_pairs
from app.services.growth import YEAR_AGO_DAYS, growth_words

PEER_WINDOW_DAYS = 45
MIN_PEERS = 5


def _d(x: date) -> str:
    return x.strftime("%b %-d, %Y")


def _money(x: float) -> str:
    return f"-${abs(x):.2f}" if x < 0 else f"${x:.2f}"


def trailing_four(pairs: list[dict]) -> tuple[float, float] | None:
    """Pure: (the last four quarters' EPS summed, the four before), when eight consecutive quarters with year-ago pairs exist."""
    head = pairs[:4]
    if len(head) < 4 or any(p["year_ago_eps"] is None for p in head):
        return None
    return sum(p["eps"] for p in head), sum(p["year_ago_eps"] for p in head)


async def sector_median_change(db, symbol: str, sector: str | None, around: date) -> tuple[float, int] | None:
    """(median percent change in EPS against a year earlier, peers counted) over the active tickers in `sector`, the ticker
    itself left out, whose latest quarter ended within PEER_WINDOW_DAYS of `around`; only peers with a positive year-ago EPS."""
    if not sector:
        return None
    rows = (await db.execute(text("""SELECT q.symbol, q.period_end, q.eps FROM eps_quarters q JOIN tickers t ON t.symbol = q.symbol
        WHERE t.is_active AND t.sector = :sec AND q.symbol <> :s AND q.period_end >= :lo ORDER BY q.symbol, q.period_end"""),
        {"sec": sector, "s": symbol, "lo": date.fromordinal(around.toordinal() - PEER_WINDOW_DAYS - YEAR_AGO_DAYS[1])})).all()
    by: dict[str, list[tuple[date, float]]] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append((r.period_end, float(r.eps)))
    changes = []
    for qs in by.values():
        pairs = year_ago_pairs(qs)
        p = pairs[0] if pairs else None
        if p and abs((p["period_end"] - around).days) <= PEER_WINDOW_DAYS and p["pct"] is not None:
            changes.append(p["pct"])
    return (round(median(changes), 1), len(changes)) if len(changes) >= MIN_PEERS else None


async def revenue_rows(db, symbol: str) -> list[dict]:
    rows = (await db.execute(text("""SELECT period_end, value, year_ago_value, phrase FROM growth_figures WHERE symbol = :s AND metric = 'revenue'
        AND held_reason IS NULL AND value IS NOT NULL ORDER BY period_end DESC LIMIT 2"""), {"s": symbol})).all()
    return [{"period_end": r.period_end, "value": float(r.value), "year_ago_value": float(r.year_ago_value), "phrase": r.phrase} for r in rows]


def _billions(x: float) -> str:
    return f"${x / 1e9:,.2f} billion" if abs(x) >= 1e9 else f"${x / 1e6:,.0f} million"


def comparison_lines(pairs: list[dict], peers: tuple[float, int] | None, sector: str | None, revenue: list[dict],
                     financials: dict | None) -> list[str]:
    """Pure: one line per comparison, each with both sides and its source."""
    out: list[str] = []
    for p in pairs[:4]:
        if p["year_ago_eps"] is None:
            continue
        out.append(f"Diluted EPS (SEC filings), quarter ended {_d(p['period_end'])}: {_money(p['eps'])} against {_money(p['year_ago_eps'])} "
                   f"in the quarter ended {_d(p['year_ago_end'])}, {p['phrase']}.")
    t4 = trailing_four(pairs)
    if t4:
        _, phrase = growth_words("eps", t4[0], t4[1])
        out.append(f"Diluted EPS over the last four quarters (SEC filings): {_money(t4[0])} against {_money(t4[1])} over the four quarters before, {phrase}.")
    if peers and pairs and pairs[0]["pct"] is not None:
        out.append(f"Sector peers ({sector}, {peers[1]} companies with both quarters on file): median EPS change against the same quarter a year "
                   f"earlier {peers[0]:+.1f}%, against {pairs[0]['pct']:+.1f}% for this company in the quarter ended {_d(pairs[0]['period_end'])}.")
    for r in revenue:
        out.append(f"Revenue (SEC filings, two readers agree), quarter ended {_d(r['period_end'])}: {_billions(r['value'])} against "
                   f"{_billions(r['year_ago_value'])} a year earlier, {r['phrase']}.")
    f = financials or {}
    for label, ttm, five in (("Gross margin", "gross_margin_ttm", "gross_margin_5y"), ("Operating margin", "operating_margin_ttm", "operating_margin_5y"),
                             ("Net margin", "net_margin_ttm", "net_margin_5y")):
        if f.get(ttm) is not None and f.get(five) is not None:
            out.append(f"{label} (financial data provider): {f[ttm]:.1f}% over the trailing twelve months against a five-year average of {f[five]:.1f}%.")
    return out


async def comparison_block(db, symbol: str, sector: str | None, financials: dict | None) -> str:
    """The COMPARISON FACTS block both prompts carry; a line saying none are on file when there are none."""
    pairs = year_ago_pairs(await load_quarters(db, symbol))
    peers = await sector_median_change(db, symbol, sector, pairs[0]["period_end"]) if pairs else None
    lines = comparison_lines(pairs, peers, sector, await revenue_rows(db, symbol), financials)
    if not lines:
        return "COMPARISON FACTS: (none on file)"
    return "COMPARISON FACTS (computed by the system from stored, dated sources; authoritative):\n" + "\n".join(f"  - {x}" for x in lines)
