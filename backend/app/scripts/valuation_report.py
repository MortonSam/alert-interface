"""Valuation report (read-only, prints; nothing is stored or displayed until approved): trailing P/E by services/valuation.

For each ticker: the fresh window (XBRL quarterly GAAP diluted EPS, or three XBRL quarters plus the stored release figure
when the company has reported a quarter XBRL does not hold; no P/E when the latest quarter cannot be read), the period it
covers, Intrinio's price-to-earnings data point beside it (live, comparison only), the five-year history summary (median
and the share of sessions today's P/E sits above, with the excluded sessions counted) and the GICS sector median over the
sector's active tickers with a fresh window.

    python -m app.scripts.valuation_report MU MSFT NVDA JPM XOM
"""
from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import valuation as V
from app.services.edgar_client import EdgarClient
from app.services.redact import redact


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


async def load_context(symbols: list[str], today: date) -> dict:
    async with ScriptSessionLocal() as s:
        sectors = dict((await s.execute(text("SELECT symbol, sector FROM tickers WHERE symbol = ANY(:s)"), {"s": symbols})).all())
        peers = (await s.execute(text("SELECT symbol, sector FROM tickers WHERE is_active AND sector = ANY(:sec) ORDER BY symbol"), {"sec": list({v for v in sectors.values() if v})})).all()
        every = sorted({p[0] for p in peers} | set(symbols))
        closes = dict((await s.execute(text("SELECT DISTINCT ON (symbol) symbol, close FROM price_bars_shadow WHERE symbol = ANY(:s) ORDER BY symbol, date DESC"), {"s": every})).all())
        last_bar = (await s.execute(text("SELECT max(date) FROM price_bars_shadow WHERE symbol = ANY(:s)"), {"s": symbols})).scalar()
        # the latest reported quarter: a confirmed or EPS-bearing earnings event, or a stored reaction row (a report that happened)
        latest_report = dict((await s.execute(text("""
            SELECT symbol, max(d) FROM (
                SELECT t.symbol, e.event_date AS d FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE t.symbol = ANY(:s) AND e.event_type = 'earnings' AND e.event_date <= :t AND (e.is_confirmed OR e.eps_actual IS NOT NULL)
                UNION ALL
                SELECT t.symbol, hr.event_date FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
                WHERE t.symbol = ANY(:s) AND hr.event_type = 'earnings' AND hr.event_date <= :t) x GROUP BY symbol"""), {"s": every, "t": today})).all())
        rel_rows = (await s.execute(text("SELECT symbol, report_date, period_end, diluted_eps_gaap, accession, how FROM release_eps WHERE symbol = ANY(:s) ORDER BY report_date"), {"s": every})).all()
        releases = {r[0]: {"report_date": r[1], "period_end": r[2], "eps": float(r[3]), "accession": r[4], "how": r[5]} for r in rel_rows}
        bars = {}
        for sym in symbols:
            rows = (await s.execute(text("SELECT date, close FROM price_bars_shadow WHERE symbol = :s AND date >= :d ORDER BY date"), {"s": sym, "d": today - timedelta(days=366 * V.RANGE_YEARS)})).all()
            bars[sym] = [(d, float(c)) for d, c in rows]
    return {"sectors": sectors, "peers": peers, "closes": {k: float(v) for k, v in closes.items() if v is not None}, "last_bar": last_bar, "latest_report": latest_report, "releases": releases, "bars": bars}


def release_for(releases: dict, sym: str, latest_report: date | None) -> dict | None:
    r = releases.get(sym)
    return r if r and latest_report and r["report_date"] == latest_report else None


async def main(argv: list[str]) -> int:
    symbols = [a.upper() for a in argv if not a.startswith("--")] or ["MU", "MSFT", "NVDA", "JPM", "XOM"]
    today = date.today()
    ctx = await load_context(symbols, today)
    print(f"Valuation report {today}; prices are stored closes through {ctx['last_bar']}; EPS from SEC XBRL company facts (GAAP diluted) and stored release figures (release_eps).\n")
    edgar = EdgarClient()
    quarters_by: dict[str, list[dict]] = {}
    windows: dict[str, list[dict] | None] = {}
    try:
        from app.services.intrinio_client import IntrinioClient
        intrinio = IntrinioClient()
        for sym in symbols:
            price = ctx["closes"].get(sym)
            try:
                cik = await edgar.get_cik(sym)
                quarters_by[sym] = V.eps_quarters(await company_facts_merged(edgar, cik)) if cik else []
            except Exception as exc:
                print(f"{sym}: XBRL failed: {redact(exc)[:120]}"); quarters_by[sym] = []
            qs = quarters_by[sym]
            lr = ctx["latest_report"].get(sym)
            rel = release_for(ctx["releases"], sym, lr)
            four, why = V.fresh_window(qs, lr, rel, today)
            windows[sym] = four
            print(f"== {sym} ({ctx['sectors'].get(sym)}) close {price}; latest reported quarter: report of {lr}")
            if not four:
                print(f"  no P/E: {why}"); continue
            ours = V.pe(price, four)
            print(f"  window ({why}): {V.period_label(four)}: " + ", ".join(
                f"{x['end']} {x['eps']:+.2f}" + (" (Q4 derived from the 10-K)" if x["derived"] else "") + (f" [{x['form']} filed {x['filed']}]" if x["source"] == "xbrl" else f" [release {rel['accession']}, {rel['how']}]")
                for x in four) + f" -> EPS {sum(x['eps'] for x in four):.2f}, P/E {ours}")
            try:
                ipe = await intrinio._get(f"/companies/{sym}/data_point/pricetoearnings/number", {})
                if isinstance(ipe, (int, float)) and price:
                    print(f"  Intrinio price-to-earnings data point: {ipe} (implies EPS {price / float(ipe):.2f} at our close); difference {float(ipe) - ours:+.2f}")
                else:
                    print(f"  Intrinio price-to-earnings data point: not a number ({str(ipe)[:80]})")
            except Exception as exc:
                print(f"  Intrinio: {redact(exc)[:80]}")
            h = V.pe_history(ctx["bars"][sym], qs, ours)
            if h["sessions"]:
                print(f"  five years ({h['first']} to {h['last']}): median P/E {h['median']}, today's {ours} is above {h['share_above']}% of {h['sessions']} sessions; "
                      f"{h['excluded']} session(s) excluded (trailing EPS negative or under {V.MIN_EARNINGS_YIELD:.0%} of price)")
            else:
                print("  five years: no sessions with a usable trailing EPS")
        await intrinio.close()
        by_sector: dict[str, list[tuple[str, float]]] = {}
        no_window: dict[str, int] = {}
        for sym, sec in ctx["peers"]:
            try:
                qs = quarters_by.get(sym)
                if qs is None:
                    cik = await edgar.get_cik(sym)
                    qs = V.eps_quarters(await company_facts_merged(edgar, cik)) if cik else []
                    quarters_by[sym] = qs
                lr = ctx["latest_report"].get(sym)
                four, _ = V.fresh_window(qs, lr, release_for(ctx["releases"], sym, lr), today)
                v = V.pe(ctx["closes"].get(sym), four)
                if v is None:
                    no_window[sec] = no_window.get(sec, 0) + 1
                else:
                    by_sector.setdefault(sec, []).append((sym, v))
            except Exception as exc:
                print(f"  peer {sym}: {redact(exc)[:80]}"); no_window[sec] = no_window.get(sec, 0) + 1
        print()
        for sec, rows in by_sector.items():
            vals = sorted(v for _, v in rows)
            med = statistics.median(vals)
            total = sum(1 for _, s2 in ctx["peers"] if s2 == sec)
            print(f"Sector {sec}: median trailing P/E {med:.1f} over {len(vals)} of {total} active tickers (the rest have no fresh window or no positive trailing EPS: {no_window.get(sec, 0)})")
            for sym in symbols:
                if ctx["sectors"].get(sym) != sec or windows.get(sym) is None:
                    continue
                ours = V.pe(ctx["closes"].get(sym), windows[sym])
                if ours is not None:
                    print(f"  {sym}: {ours} vs sector median {med:.1f} ({ours / med:.2f}x); higher than {sum(1 for v in vals if v < ours) / len(vals) * 100:.0f}% of the sector")
    finally:
        await edgar.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
