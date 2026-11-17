"""Before and after for Sam's item 8 (the one-year change, services/one_year), read-only over a database copy. Revised 2026-11-16:
spin-offs counted as a holder saw them (services/one_year.holder_adjusted); split_only is the figure the first version (6d78160) gave.

    python ops/tools/one_year_before_after.py YYYY-MM-DD OUT.csv

Surfaces, per stock unless named:
  walkthrough_stock_1y         step 4's "<name> over one year": before, 252 sessions back on dividend-adjusted closes (SPY's calendar);
                               after, W.step_stock as built now. stored = the stored walkthrough's cell, for a cross-check.
  ticker_header_1y             the ticker page's 1Y header: before, the latest close (the quote when the market is shut) against the first
                               dividend-adjusted close on or after the day 366 days before the date given; after, the chart's one_year.
  walkthrough_sector_median_1y step 4's median sector stock (symbol = the sector)
  walkthrough_spy_1y           step 4's S&P 500 (SPY) line
  walkthrough_stock_3m         step 4's three months (63 sessions, unchanged), now on the same holder-adjusted closes as its year
  walkthrough_pe_year          step 5's P/E year: "kept" or "absent: spin-off in the year" (after only)
Nothing is written to the database.
"""
from __future__ import annotations

import asyncio
import csv
import sys
from datetime import date, timedelta
from statistics import median

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import price_bars
from app.services import walkthrough as W
from app.services import walkthrough_data as D
from app.services.one_year import holder_adjusted, one_year_change

OLD_YEAR_SESSIONS = 252


def old_change(series, sessions=OLD_YEAR_SESSIONS):
    if len(series) <= sessions:
        return None
    (d0, c0), (d1, c1) = series[-sessions - 1], series[-1]
    return (round((c1 / c0 - 1) * 100, 1), d0, d1) if c0 > 0 else None


def old_step4(stock, spy, today, sessions=OLD_YEAR_SESSIONS):
    cal = [d for d, _ in spy[-OLD_YEAR_SESSIONS - 1:]]
    if not cal or (today - cal[-1]).days > D.STALE_BAR_DAYS:
        return None
    a = D.aligned(stock, cal)
    if a is None or len(a) < len(cal):
        return None
    return old_change([(d, a[d]) for d in cal], sessions)


def old_sectors(tickers, closes, spy):
    cal = [d for d, _ in spy[-OLD_YEAR_SESSIONS - 1:]]
    by: dict[str, list] = {}
    for sym, t in tickers.items():
        if not t.get("index_member") or not t.get("sector"):
            continue
        a = D.aligned(closes.get(sym, []), cal)
        if a is None or len(a) != len(cal):
            continue
        by.setdefault(t["sector"], []).append(a)
    return {sec: (round(median((m[cal[-1]] / m[cal[0]] - 1) * 100 for m in ms), 1), len(ms), cal[0]) for sec, ms in by.items() if len(ms) >= 3}


def pct_cell(v):
    return None if v is None else float(str(v).replace("%", "").replace(",", "").replace("+", "").replace("−", "-"))


def split_only(today):
    """{symbol: closes adjusted for splits alone}: the first version's series (6d78160), for the split_only column."""
    from app.services.valuation import split_ratio
    start = today - timedelta(days=D.BARS_LOOKBACK_DAYS)
    with price_bars._engine().connect() as conn:
        raw = conn.execute(text("SELECT symbol, date, close FROM price_bars_shadow WHERE date >= :d AND close IS NOT NULL ORDER BY symbol, date"), {"d": start}).all()
        sp = conn.execute(text("""SELECT t.symbol, e.event_date, e.metadata->>'split_ratio' FROM events e JOIN tickers t ON t.id = e.ticker_id
                                  WHERE e.event_type = 'split' AND e.event_date > :d"""), {"d": start}).all()
    by, splits = {}, {}
    for r in raw:
        by.setdefault(r[0], []).append((r[1], float(r[2])))
    for r in sp:
        splits.setdefault(r[0], []).append((r[1], split_ratio(r[2])))
    return {sym: holder_adjusted(rs, splits.get(sym, [])) for sym, rs in by.items()}


async def main(today: date, out: str) -> int:
    async with ScriptSessionLocal() as db:
        u = await D.load_universe(db, today)
        stored = {r.symbol: r.payload for r in (await db.execute(text("SELECT symbol, payload FROM ivy_walkthroughs"))).all()}
        spun = {r[0] for r in (await db.execute(text("""SELECT DISTINCT t.symbol FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE (e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata->>'corporate_action' = 'spin_off')) AND e.event_date > :d"""),
                {"d": today - timedelta(days=D.BARS_LOOKBACK_DAYS)})).all()}
    first = split_only(today)
    first_spy = first.get("SPY", [])
    first_sectors = D.sector_changes(u["tickers"], first, first_spy)
    rows = []
    spy_adj = u["spy"]
    for sym, t in sorted(u["tickers"].items()):
        stock_adj = u["closes"].get(sym, [])
        old = old_step4(stock_adj, spy_adj, today)
        st = W.step_stock(sym, t.get("sector"), u["holder_closes"].get(sym, []), u["spy_holder"], u["sectors"].get(t.get("sector")), [], 0.5, today)
        new = st.get("year_pct") if st["status"] != "absent" else None
        new_start = st["chart"]["start"] if st.get("chart") else None
        f4 = W.step_stock(sym, t.get("sector"), first.get(sym, []), first_spy, first_sectors.get(t.get("sector")), [], 0.5, today)
        if sym in spun and st.get("year_start"):
            acts = u["actions"].get(sym, [])
            inside = any(a["kind"] == "spin_off" and a["date"] > st["year_start"] for a in acts)
            rows.append({"surface": "walkthrough_pe_year", "symbol": sym, "old": None, "new": None, "split_only": None, "old_start": None,
                         "new_start": None, "end": None, "stored": None, "note": "absent: spin-off in the year" if inside else "kept"})
        cell = (((stored.get(sym) or {}).get("steps") or [{}] * 4)[3].get("cell") or {}).get("close") or {}
        rows.append({"surface": "walkthrough_stock_1y", "symbol": sym, "old": old[0] if old else None, "new": new,
                     "split_only": f4.get("year_pct") if f4["status"] != "absent" else None,
                     "old_start": old[1] if old else None, "new_start": new_start, "end": old[2] if old else (st.get("chart") or {}).get("as_of"),
                     "stored": pct_cell(cell.get("value"))})
        o3 = old_step4(stock_adj, spy_adj, today, D.QUARTER_SESSIONS)
        n3 = next((n["value"] for n in st.get("deeper", []) if n["label"] == f"{sym} over three months"), None) if st["status"] != "absent" else None
        rows.append({"surface": "walkthrough_stock_3m", "symbol": sym, "old": o3[0] if o3 else None, "new": pct_cell(n3),
                     "split_only": None, "old_start": o3[1] if o3 else None, "new_start": None, "end": o3[2] if o3 else None, "stored": None})
        # the ticker page's 1Y header
        lo = today - timedelta(days=price_bars.PERIOD_DAYS["1y"])
        adj = [(d, c) for d, c in stock_adj if d >= lo]
        last_raw = u["holder_closes"].get(sym, [])[-1:]           # the last close as traded (adjusted = raw on the latest day)
        h_old = (round((last_raw[0][1] / adj[0][1] - 1) * 100, 2), adj[0][0]) if adj and last_raw else None
        oy = one_year_change(u["holder_closes"].get(sym, []))
        fy = one_year_change(first.get(sym, []))
        rows.append({"surface": "ticker_header_1y", "symbol": sym, "old": h_old[0] if h_old else None, "new": round(oy["pct"], 2) if oy else None,
                     "split_only": round(fy["pct"], 2) if fy else None,
                     "old_start": h_old[1] if h_old else None, "new_start": oy["start_date"] if oy else None,
                     "end": oy["end_date"] if oy else (last_raw[0][0] if last_raw else None), "stored": None})
    olds = old_sectors(u["tickers"], u["closes"], spy_adj)
    for sec in sorted(set(olds) | set(u["sectors"])):
        o, n = olds.get(sec), u["sectors"].get(sec)
        f = first_sectors.get(sec)
        rows.append({"surface": "walkthrough_sector_median_1y", "symbol": sec, "old": o[0] if o else None, "new": n["change_1y"] if n else None,
                     "split_only": f["change_1y"] if f else None,
                     "old_start": o[2] if o else None, "new_start": n["start"] if n else None, "end": n["end"] if n else None, "stored": None})
    po, pn = old_change(spy_adj), D.year_change(u["spy_holder"])
    fs = D.year_change(first_spy)
    rows.append({"surface": "walkthrough_spy_1y", "symbol": "SPY", "old": po[0] if po else None, "new": pn[0] if pn else None,
                 "split_only": fs[0] if fs else None,
                 "old_start": po[1] if po else None, "new_start": pn[1] if pn else None, "end": pn[2] if pn else None, "stored": None})
    for r in rows:
        r["diff"] = round(r["new"] - r["old"], 2) if r["old"] is not None and r["new"] is not None else None
        r["changed_over_0_1"] = (r["diff"] is not None and abs(r["diff"]) > 0.1) or ((r["old"] is None) != (r["new"] is None))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["surface", "symbol", "old", "split_only", "new", "diff", "changed_over_0_1", "old_start", "new_start", "end",
                                          "stored", "note"], restval="")
        w.writeheader()
        w.writerows(rows)
    for surface in ("walkthrough_stock_1y", "ticker_header_1y", "walkthrough_sector_median_1y", "walkthrough_spy_1y", "walkthrough_stock_3m"):
        rs = [r for r in rows if r["surface"] == surface]
        print(f"{surface}: {len(rs)} rows, {sum(r['changed_over_0_1'] for r in rs)} change by more than 0.1 point or appear/disappear, "
              f"{sum(1 for r in rs if r['old'] is not None and r['new'] is not None and (r['old'] > 0) != (r['new'] > 0))} change sign")
    for r in rows:
        if r["symbol"] in ("LLY", "GOOGL", "SPY") or r["symbol"] in spun:
            print(r)
    mism = [r for r in rows if r["surface"] == "walkthrough_stock_1y" and r["stored"] is not None and r["old"] is not None and abs(r["stored"] - r["old"]) > 0.05]
    print(f"stored walkthrough cells not matching the before figure: {len(mism)}", [(r['symbol'], r['stored'], r['old']) for r in mism[:10]])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(date.fromisoformat(sys.argv[1]), sys.argv[2])))
