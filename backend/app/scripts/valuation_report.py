"""Valuation report (read-only, prints; nothing is stored or displayed): trailing P/E computed by us as the latest stored
close over the sum of the last four reported quarters' GAAP diluted EPS from SEC XBRL company facts, topped up with the
latest earnings release (events.eps_actual) when it is newer than the last 10-Q/10-K, always with the period it covers.
Beside it: Intrinio's price-to-earnings data point (live, for comparison only), our P/E against its own five-year range
(point-in-time: each day's close over the four quarters filed by that day) and the GICS sector median of our P/E over the
sector's active tickers (XBRL only, no release top-up).

    python -m app.scripts.valuation_report MU MSFT NVDA JPM XOM
"""
from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import EdgarClient
from app.services.redact import redact

QUARTER_DAYS = (80, 100)       # a quarterly EPS fact covers a period this long
YEAR_DAYS = (350, 380)         # an annual one
RANGE_YEARS = 5


def _d(s: str) -> date:
    return date.fromisoformat(s)


def eps_quarters(facts: dict) -> list[dict]:
    """Pure: quarterly GAAP diluted EPS from a companyfacts document: the quarterly facts themselves, plus the fourth quarter
    derived as the fiscal year's annual figure less the three quarters inside it. Each: {end, start, eps, filed, form, derived}.
    One value per period end, the latest filed wins."""
    series = (facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", []))
    quarters: dict[date, dict] = {}
    annual: list[dict] = []
    for e in series:
        try:
            start, end, filed = _d(e["start"]), _d(e["end"]), _d(e["filed"])
        except (KeyError, ValueError):
            continue
        days = (end - start).days
        row = {"end": end, "start": start, "eps": float(e["val"]), "filed": filed, "form": e.get("form", ""), "fy": e.get("fy"), "fp": e.get("fp"), "derived": False}
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
            q4 = {"end": a["end"], "start": max(q["end"] for q in inside) + timedelta(days=1), "eps": round(a["eps"] - sum(q["eps"] for q in inside), 4),
                  "filed": a["filed"], "form": a["form"], "fy": a["fy"], "fp": "Q4", "derived": True}
            quarters[a["end"]] = q4
    return sorted(quarters.values(), key=lambda q: q["end"])


def trailing_four(quarters: list[dict], as_of: date, known_by: date | None = None) -> list[dict] | None:
    """Pure: the four most recent quarters ending on or before as_of and filed by known_by (point in time), oldest first; None if fewer."""
    known_by = known_by or as_of
    eligible = [q for q in quarters if q["end"] <= as_of and q["filed"] <= known_by]
    return eligible[-4:] if len(eligible) >= 4 else None


def pe(price: float | None, four: list[dict] | None) -> float | None:
    if price is None or not four:
        return None
    total = sum(q["eps"] for q in four)
    return round(price / total, 2) if total > 0 else None


def period_label(four: list[dict]) -> str:
    return f"{four[0]['start'].isoformat()} to {four[-1]['end'].isoformat()}"


async def company_facts_merged(edgar: EdgarClient, cik: str) -> dict:
    """Company facts for a CIK plus those of any earlier CIK its filings were made under (the accession prefix names the
    filer: Exxon Mobil's 2026 holding-company CIK carries four facts, its history sits under 0000034088)."""
    facts = await edgar.get_company_facts(cik)
    series = facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", [])
    others = {e.get("accn", "")[:10] for e in series if e.get("accn") and e["accn"][:10] != cik.zfill(10) and e["accn"][:10].isdigit()}
    for other in others:
        try:
            more = (await edgar.get_company_facts(other)).get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", [])
        except Exception:
            continue
        series.extend(more)
    if series:
        facts.setdefault("facts", {}).setdefault("us-gaap", {}).setdefault("EarningsPerShareDiluted", {}).setdefault("units", {})["USD/shares"] = series
    return facts


async def main(argv: list[str]) -> int:
    symbols = [a.upper() for a in argv if not a.startswith("--")] or ["MU", "MSFT", "NVDA", "JPM", "XOM"]
    today = date.today()
    edgar = EdgarClient()
    async with ScriptSessionLocal() as s:
        sectors = dict((await s.execute(text("SELECT symbol, sector FROM tickers WHERE symbol = ANY(:s)"), {"s": symbols})).all())
        peers = (await s.execute(text("SELECT symbol, sector FROM tickers WHERE is_active AND sector = ANY(:sec) ORDER BY symbol"), {"sec": list({v for v in sectors.values() if v})})).all()
        closes = dict((await s.execute(text("""SELECT DISTINCT ON (symbol) symbol, close FROM price_bars_shadow WHERE symbol = ANY(:s) ORDER BY symbol, date DESC"""),
                                       {"s": [p[0] for p in peers] + symbols})).all())
        last_bar = (await s.execute(text("SELECT max(date) FROM price_bars_shadow WHERE symbol = ANY(:s)"), {"s": symbols})).scalar()
        releases = {}
        for sym in symbols:
            r = (await s.execute(text("""SELECT e.event_date, e.eps_actual, e.eps_source FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.eps_actual IS NOT NULL AND e.event_date <= :t ORDER BY e.event_date DESC LIMIT 1"""), {"s": sym, "t": today})).first()
            if r:
                releases[sym] = {"date": r[0], "eps": float(r[1]), "source": r[2]}
        bars = {}
        for sym in symbols:
            rows = (await s.execute(text("SELECT date, close FROM price_bars_shadow WHERE symbol = :s AND date >= :d ORDER BY date"),
                                    {"s": sym, "d": today - timedelta(days=366 * RANGE_YEARS)})).all()
            bars[sym] = [(d, float(c)) for d, c in rows]
    print(f"Valuation report {today}; prices are stored closes through {last_bar}; EPS from SEC XBRL company facts (GAAP diluted).\n")
    quarters_by: dict[str, list[dict]] = {}
    try:
        from app.services.intrinio_client import IntrinioClient
        intrinio = IntrinioClient()
        for sym in symbols:
            try:
                cik = await edgar.get_cik(sym)
                quarters_by[sym] = eps_quarters(await company_facts_merged(edgar, cik)) if cik else []
            except Exception as exc:
                print(f"{sym}: XBRL failed: {redact(exc)[:120]}"); quarters_by[sym] = []
            q = quarters_by[sym]
            price = float(closes[sym]) if closes.get(sym) is not None else None
            four = trailing_four(q, today)
            print(f"== {sym} ({sectors.get(sym)}) close {price}")
            if not four:
                print("  fewer than four reported quarters in XBRL"); continue
            print(f"  XBRL trailing four ({period_label(four)}): " + ", ".join(f"{x['end']} {x['eps']:+.2f}{' (Q4 derived from the 10-K)' if x['derived'] else ''} [{x['form']} filed {x['filed']}]" for x in four)
                  + f" -> EPS {sum(x['eps'] for x in four):.2f}, P/E {pe(price, four)}")
            rel = releases.get(sym)
            if rel and rel["date"] > four[-1]["end"]:
                topped = four[1:] + [{"end": rel["date"], "start": four[-1]["end"] + timedelta(days=1), "eps": rel["eps"], "filed": rel["date"], "form": f"earnings release ({rel['source']})", "derived": False}]
                print(f"  with the latest release ({rel['date']}, EPS {rel['eps']:+.2f} per events.eps_actual, source {rel['source']}; basis not verified as GAAP): "
                      f"period {period_label(topped)} -> EPS {sum(x['eps'] for x in topped):.2f}, P/E {pe(price, topped)}")
            try:
                ipe = await intrinio._get(f"/companies/{sym}/data_point/pricetoearnings/number", {})
                ours = pe(price, four)
                if isinstance(ipe, (int, float)):
                    print(f"  Intrinio price-to-earnings data point: {ipe} (implies EPS {price / float(ipe):.2f} at our close)" + (f"; difference {float(ipe) - ours:+.2f}" if ours else ""))
                else:
                    print(f"  Intrinio price-to-earnings data point: not a number ({str(ipe)[:120]})")
            except Exception as exc:
                print(f"  Intrinio: {redact(exc)[:80]}")
            series = []
            for d, c in bars[sym]:
                f4 = trailing_four(q, d, d)
                v = pe(c, f4)
                if v is not None:
                    series.append((d, v))
            if series:
                vals = [v for _, v in series]
                cur = pe(price, four)
                below = sum(1 for v in vals if v < cur) / len(vals) * 100 if cur else None
                lo, hi = min(series, key=lambda x: x[1]), max(series, key=lambda x: x[1])
                print(f"  five-year range of our P/E ({series[0][0]} to {series[-1][0]}, {len(vals)} sessions): low {lo[1]} on {lo[0]}, high {hi[1]} on {hi[0]}, median {statistics.median(vals):.1f}; "
                      f"current {cur} is above {below:.0f}% of those sessions")
        await intrinio.close()
        # sector medians from XBRL only
        by_sector: dict[str, list[tuple[str, float]]] = {}
        for sym, sec in peers:
            try:
                qs = quarters_by.get(sym)
                if qs is None:
                    cik = await edgar.get_cik(sym)
                    qs = eps_quarters(await company_facts_merged(edgar, cik)) if cik else []
                    quarters_by[sym] = qs
                v = pe(float(closes[sym]) if closes.get(sym) is not None else None, trailing_four(qs, today))
                if v is not None:
                    by_sector.setdefault(sec, []).append((sym, v))
            except Exception as exc:
                print(f"  peer {sym}: {redact(exc)[:80]}")
        print()
        for sec, rows in by_sector.items():
            vals = sorted(v for _, v in rows)
            med = statistics.median(vals)
            names = [sym for sym in symbols if sectors.get(sym) == sec]
            print(f"Sector {sec}: median trailing P/E {med:.1f} over {len(vals)} tickers with positive trailing EPS (of {sum(1 for _, s2 in peers if s2 == sec)} active)")
            for sym in names:
                ours = pe(float(closes[sym]) if closes.get(sym) is not None else None, trailing_four(quarters_by.get(sym, []), today))
                if ours is not None:
                    rank = sum(1 for v in vals if v < ours) / len(vals) * 100
                    print(f"  {sym}: {ours} vs sector median {med:.1f} ({ours / med:.2f}x); higher than {rank:.0f}% of the sector")
    finally:
        await edgar.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
