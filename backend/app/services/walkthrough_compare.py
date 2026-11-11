"""Compare's two choices (a rival and a familiar ruler) and the home page's featured stock, each chosen by a written rule.
"Market value" is the company's own figure on file (services/market_value), never the vendor's market cap: a company with no
figure (the hold-out list) has no rival, is no one's rival and is never featured, and another share class of the same company
(GOOG beside GOOGL) is not a rival.

RIVAL_RULE: the active S&P 500 stock in the same GICS sub-industry whose market value is closest to this one's (by ratio, so
$1.0 trillion against $1.5 trillion is as close as $100 billion against $150 billion); a tie goes to the larger. A sub-industry
with no other member falls back to the same GICS sector, and the label says so.
RULER: Apple, the familiar ruler; for Apple itself, Microsoft.
FEATURED_RULE: each night, among S&P 500 stocks whose walkthrough shows all seven steps as served, the largest by market value
with a company-confirmed report in the next FEATURED_REPORT_DAYS days; when none qualifies, the largest by market value not
featured in the last FEATURED_REPEAT_DAYS days.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

RULER = "AAPL"
RULER_FOR_RULER = "MSFT"
FEATURED_REPORT_DAYS = 14
FEATURED_REPEAT_DAYS = 30
RIVAL_RULE = ("Same GICS sub-industry, closest market value by ratio; a tie goes to the larger. With no other stock in the sub-industry, "
              "the same sector.")
FEATURED_RULE = (f"Among S&P 500 stocks whose walkthrough shows all seven steps, the largest by market value with a company-confirmed report "
                 f"in the next {FEATURED_REPORT_DAYS} days; when none qualifies, the largest not featured in the last {FEATURED_REPEAT_DAYS} days.")


def rival_for(symbol: str, tickers: dict[str, dict], available: set[str]) -> dict | None:
    """Pure: {symbol, basis ("sub-industry" | "sector")} for the closest-valued stock in the same sub-industry (else sector) that has a
    walkthrough; None without a market value or a peer. tickers is {symbol: {symbol, industry, sector, index_member, market_value,
    company}} (market_value_store.TICKERS_WITH_VALUE)."""
    me = tickers.get(symbol)
    if not me or not me.get("market_value"):
        return None
    mine = me.get("company") or symbol
    for basis, field in (("sub-industry", "industry"), ("sector", "sector")):
        peers = [t for s, t in tickers.items() if s != symbol and s in available and t.get("index_member") and t.get(field) and t.get(field) == me.get(field)
                 and t.get("market_value") and (t.get("company") or s) != mine]
        if peers:
            best = min(peers, key=lambda t: (abs(math.log(t["market_value"] / me["market_value"])), -t["market_value"], t["symbol"]))
            return {"symbol": best["symbol"], "basis": basis}
    return None


def ruler_for(symbol: str) -> str:
    return RULER_FOR_RULER if symbol == RULER else RULER


def served_steps(payload: dict, growth_on: bool, pe_on: bool) -> int:
    """Pure: steps a visitor sees with data, after the flags (routers/walkthrough.gate) hide growth or the P/E."""
    return sum(1 for s in payload["steps"] if s["status"] != "absent" and not (s["key"] == "growth" and not growth_on)
               and not (s["key"] == "valuation" and not pe_on and not payload.get("reit")))


def choose_featured(cands: list[dict], today: date, history: list[dict]) -> dict | None:
    """Pure: FEATURED_RULE over [{symbol, market_value, full (all seven steps served), next_date, confirmed}]; history is
    [{symbol, date}] of past picks. Two classes of one company carry the same figure: the first symbol in the alphabet stands."""
    from app.services.briefing import fmt_date
    full = sorted((c for c in cands if c["full"] and c.get("market_value")), key=lambda c: c["symbol"])
    soon = [c for c in full if c.get("confirmed") and c.get("next_date") and today <= c["next_date"] <= today + timedelta(days=FEATURED_REPORT_DAYS)]
    if soon:
        c = max(soon, key=lambda c: c["market_value"])
        return {"symbol": c["symbol"], "why": f"reports on {fmt_date(c['next_date'])}, a date the company has confirmed"}
    recent = {h["symbol"] for h in history if date.fromisoformat(str(h["date"])[:10]) > today - timedelta(days=FEATURED_REPEAT_DAYS)}
    rest = [c for c in full if c["symbol"] not in recent]
    if rest:
        c = max(rest, key=lambda c: c["market_value"])
        return {"symbol": c["symbol"], "why": "the largest not featured lately"}
    return None


def featured(built: dict, u: dict, today: date, history: list[dict] | None = None) -> dict:
    from app.config import settings
    cands = []
    for sym, b in built.items():
        t = u["tickers"][sym]
        if not t.get("index_member"):
            continue
        ne = u["next"].get(sym)
        cands.append({"symbol": sym, "market_value": t.get("market_value"), "full": served_steps(b["payload"], settings.growth_enabled, settings.pe_enabled) == 7,
                      "next_date": ne.date if ne and ne.date else None, "confirmed": bool(ne and ne.confirmation == "confirmed")})
    pick = choose_featured(cands, today, history or []) or {"symbol": None, "why": "no stock shows all seven steps"}
    return {**pick, "date": today.isoformat(), "rule": FEATURED_RULE, "history": ((history or []) + ([{"symbol": pick["symbol"], "date": today.isoformat()}] if pick.get("symbol") else []))[-FEATURED_REPEAT_DAYS:]}
