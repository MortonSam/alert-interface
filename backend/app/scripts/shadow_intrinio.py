"""Shadow comparison of stored reactions and chains against Intrinio. Read-only.

prices: for every historical_reactions row of the given tickers (earnings, FOMC, analyst), fetch Intrinio's
split- and dividend-adjusted daily bars (one request per ticker, plus SPY for the session calendar) and
recompute close_before, open_after, close_after and pct_change_1d with the seeder's own functions. A row
reproduces when the stored one-day move and the recomputed one agree within TOLERANCE_PP, or both are null.
Prints a per-ticker table, the totals, and the ten largest differences with both values and the dates.

chains: for each symbol, Intrinio's EOD chain on the courier chain's own date against the courier chain in
chain_store (the configured database; SHADOW_DB_URL names another database to read, read-only, for the
courier side): strikes present on one side only, the mid difference per shared contract, and the IV at the
ATM strike for the chain's spot and for a given quote.

Usage
-----
    python -m app.scripts.shadow_intrinio prices MU,CAT,AAPL
    python -m app.scripts.shadow_intrinio prices ALL
    python -m app.scripts.shadow_intrinio prices ALL --from-stored          # bars from price_bars_shadow, no requests
    python -m app.scripts.shadow_intrinio chains MU=1078.04,CAT=827.02       # SYMBOL=page quote for the second ATM pick
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.compute_analyst_reactions import _compute_pre_market
from app.scripts.seed_historical_reactions import _build_date_cache, _compute, _compute_v3
from app.services import chain_store
from app.services.intrinio_client import IntrinioClient
from app.services.price_bars_shadow import adjusted_frame
from app.services.security_records import Record, rests_on_stored_history

START = date(2021, 7, 1)
TOLERANCE_PP = 0.01


def frame(bars: list[dict]) -> pd.DataFrame:
    """A yfinance-shaped frame from Intrinio bars: adjusted OHLC and volume, dated index."""
    if not bars:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame([{"date": pd.Timestamp(b["date"]), "Open": b.get("adj_open"), "High": b.get("adj_high"), "Low": b.get("adj_low"),
                        "Close": b.get("adj_close"), "Volume": b.get("adj_volume") if b.get("adj_volume") is not None else b.get("volume")} for b in bars])
    df = df.dropna(subset=["Open", "Close"]).set_index("date").sort_index()
    df["Volume"] = df["Volume"].fillna(0)
    return df


def _f(v):
    return None if v is None else float(v)


def recompute(row, hist: pd.DataFrame, dates, sessions) -> dict | None:
    etype, ed, timing = row["event_type"], row["event_date"], row["report_timing"]
    try:
        if etype == "earnings":
            return _compute_v3(hist, dates, ed, timing or "unknown", sessions)
        if etype == "fomc":
            return _compute(hist, dates, ed, sessions)
        return _compute_pre_market(hist, dates, ed, sessions)
    except Exception:
        return None


async def stored_bars(symbol: str) -> pd.DataFrame:
    """The symbol's bars from price_bars_shadow, adjusted by the stored factors."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""select date, open, high, low, close, volume, factor, split_ratio
                                        from price_bars_shadow where symbol = :s order by date"""), {"s": symbol})).mappings().all()
    return adjusted_frame([dict(r) for r in rows])


async def security_records(symbols: list[str]) -> dict[str, list[Record]]:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""select symbol, intrinio_security_id, figi, composite_figi, name, valid_from, valid_to, role, source
                                        from security_records where symbol = any(:s)"""), {"s": symbols})).all()
    by: dict[str, list[Record]] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(Record(*r))
    return by


def session_before(sessions, day: date) -> date | None:
    earlier = [d for d in sessions if d < day]
    return earlier[-1] if earlier else None


async def prices(symbols: list[str], client: IntrinioClient | None, today: date) -> dict:
    """client None: every frame comes from price_bars_shadow (the nightly fetch), no requests. Rows resting on a
    stored_history span (security_records) keep their stored values and are counted, not recomputed."""
    async def bars(sym: str) -> pd.DataFrame:
        return await stored_bars(sym) if client is None else frame(await client.daily_prices(sym, START, today + timedelta(days=1)))
    spy = await bars("SPY")
    sessions = _build_date_cache(spy)
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            select t.symbol, hr.event_type::text as event_type, hr.event_date, hr.report_timing, hr.close_before, hr.open_after, hr.close_after, hr.pct_change_1d
            from historical_reactions hr join tickers t on t.id = hr.ticker_id where t.symbol = any(:s) order by t.symbol, hr.event_date"""), {"s": symbols})).mappings().all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["symbol"], []).append(r)
    records = await security_records(symbols)
    out = {"tickers": {}, "diffs": []}
    for sym in symbols:
        try:
            hist = await bars(sym)
        except Exception as exc:
            out["tickers"][sym] = {"error": str(exc)[:120]}
            continue
        if hist.empty:
            out["tickers"][sym] = {"error": "no bars"}
            continue
        dates = _build_date_cache(hist)
        stat = {"rows": 0, "reproduced": 0, "differ": 0, "stored_null": 0, "intrinio_null": 0, "stored_history": 0, "first_bar": str(dates[0])}
        for r in by.get(sym, []):
            stat["rows"] += 1
            if rests_on_stored_history(records.get(sym, []), r["event_date"], session_before(sessions, r["event_date"])):
                stat["stored_history"] += 1
                continue
            got = recompute(r, hist, dates, sessions)
            g1, s1 = (_f(got.get("pct_change_1d")) if got else None), _f(r["pct_change_1d"])
            if s1 is None and g1 is None:
                stat["reproduced"] += 1
            elif s1 is None:
                stat["stored_null"] += 1
            elif g1 is None:
                stat["intrinio_null"] += 1
                out["diffs"].append({"symbol": sym, "type": r["event_type"], "date": r["event_date"].isoformat(), "stored_1d": s1, "intrinio_1d": None, "delta": None})
            elif abs(g1 - s1) <= TOLERANCE_PP:
                stat["reproduced"] += 1
            else:
                stat["differ"] += 1
                out["diffs"].append({"symbol": sym, "type": r["event_type"], "date": r["event_date"].isoformat(), "timing": r["report_timing"], "stored_1d": s1,
                                     "intrinio_1d": round(g1, 4), "delta": round(abs(g1 - s1), 4),
                                     "stored": [_f(r["close_before"]), _f(r["open_after"]), _f(r["close_after"])],
                                     "intrinio": [_f(got.get("close_before")), _f(got.get("open_after")), _f(got.get("close_after"))]})
        out["tickers"][sym] = stat
    return out


def print_prices(out: dict, requests: int, retries: int) -> None:
    ok = {s: v for s, v in out["tickers"].items() if "error" not in v}
    print(f"\n{'ticker':6} {'rows':>5} {'repro':>6} {'differ':>6} {'s_null':>6} {'i_null':>6} {'stored':>6}  first bar")
    for sym, v in out["tickers"].items():
        if "error" in v:
            print(f"{sym:6} error: {v['error']}")
        else:
            print(f"{sym:6} {v['rows']:5} {v['reproduced']:6} {v['differ']:6} {v['stored_null']:6} {v['intrinio_null']:6} {v['stored_history']:6}  {v['first_bar']}")
    tot = {k: sum(v[k] for v in ok.values()) for k in ("rows", "reproduced", "differ", "stored_null", "intrinio_null", "stored_history")}
    print(f"\ntotals over {len(ok)} ticker(s): {tot}   requests {requests}, retries {retries}")
    print("  reproduced: stored and recomputed pct_change_1d within %.2f pp, or both null" % TOLERANCE_PP)
    print("  s_null: stored pct null where Intrinio computes a value; i_null: stored value where Intrinio has no bar")
    print("  stored: rows on a stored_history span (security_records), kept as stored (price_source yfinance), never recomputed")
    diffs = sorted((d for d in out["diffs"] if d["delta"] is not None), key=lambda d: -d["delta"])
    if diffs:
        print("\nten largest differences (stored vs Intrinio pct_change_1d; close_before/open_after/close_after):")
        for d in diffs[:10]:
            print(f"  {d['symbol']:5} {d['type']:14} {d['date']} stored {d['stored_1d']:+.4f} intrinio {d['intrinio_1d']:+.4f} delta {d['delta']:.4f}  stored {d['stored']} intrinio {d['intrinio']}")


async def _courier_chain(sym: str) -> tuple[str, dict] | None:
    """(expiration, chain) for the symbol's nearest ingested expiration, from the configured database or SHADOW_DB_URL."""
    url = os.environ.get("SHADOW_DB_URL")
    if url:
        import asyncpg
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"), timeout=25)
        try:
            keys = [r["key"] for r in await conn.fetch("select key from system_metadata where key like $1 order by key", f"chain:{sym}:%")]
            if not keys:
                return None
            return keys[0].split(":")[-1], json.loads(await conn.fetchval("select value from system_metadata where key=$1", keys[0]))
        finally:
            await conn.close()
    async with ScriptSessionLocal() as s:
        exps = await chain_store.get_ingested_expirations(s, sym)
        if not exps:
            return None
        got = await chain_store.get_chain(s, sym, exps[0])
        return (exps[0], got[0]) if got else None


def _mid(bid, ask, fallback=None):
    return (bid + ask) / 2 if bid and ask else fallback


async def chains(targets: dict[str, float | None], client: IntrinioClient) -> None:
    for sym, quote in targets.items():
        got = await _courier_chain(sym)
        if got is None:
            print(f"\n== {sym}: no courier chain in chain_store")
            continue
        exp, courier = got
        on = date.fromisoformat(str(courier.get("chain_last_trade"))[:10]) if courier.get("chain_last_trade") else None
        chain = await client.options_chain_eod(sym, exp, on)
        print(f"\n== {sym} expiration {exp}: courier chain dated {courier.get('chain_last_trade')} spot {courier.get('underlying_price')}; "
              f"Intrinio EOD {on}: {len(chain)} contracts, dates {sorted({c['prices'].get('date') for c in chain})}")
        bid_times = sorted({c["prices"].get("close_bid_time") or "" for c in chain if c["prices"].get("close_bid_time")})
        if bid_times:
            print(f"   Intrinio quote stamps (close_bid_time) {bid_times[0]} .. {bid_times[-1]}")
        mids, ivs = [], []
        for side, key in (("call", "calls"), ("put", "puts")):
            cour = {float(c["strike"]): c for c in courier.get(key, [])}
            intr = {float(c["option"]["strike"]): c["prices"] for c in chain if c["option"]["type"] == side}
            shared = sorted(set(cour) & set(intr))
            print(f"   {side}s: shared {len(shared)}, courier-only {sorted(set(cour) - set(intr))[:10]}, intrinio-only {len(set(intr) - set(cour))} strikes")
            for k in shared:
                cm, im = _mid(cour[k].get("bid"), cour[k].get("ask")), _mid(intr[k].get("close_bid"), intr[k].get("close_ask"), intr[k].get("mark"))
                if cm is not None and im is not None:
                    mids.append((side, k, cm, im, im - cm))
                if cour[k].get("impliedVolatility") is not None and intr[k].get("implied_volatility") is not None:
                    ivs.append(intr[k]["implied_volatility"] - cour[k]["impliedVolatility"])
        if mids:
            deltas = [m[4] for m in mids]
            print(f"   mid difference (Intrinio minus courier) over {len(mids)} shared: median {statistics.median(deltas):+.3f}, mean abs {statistics.mean(abs(x) for x in deltas):.3f}, "
                  f"within $0.25: {sum(1 for x in deltas if abs(x) <= 0.25)}; largest {sorted(mids, key=lambda m: -abs(m[4]))[:3]}")
        if ivs:
            print(f"   IV difference over {len(ivs)} shared: median {statistics.median(ivs):+.4f}, mean abs {statistics.mean(abs(x) for x in ivs):.4f}")
        strikes = {float(c["strike"]) for c in courier.get("calls", [])} & {float(p["strike"]) for p in courier.get("puts", [])}
        for label, spot in (("chain spot", courier.get("underlying_price")), ("quote", quote)):
            if spot is None or not strikes:
                continue
            atm = min(strikes, key=lambda s: abs(s - spot))
            print(f"   ATM by {label} {spot}: strike {atm}")
            for side, key in (("call", "calls"), ("put", "puts")):
                c = next((x for x in courier[key] if float(x["strike"]) == atm), None)
                i = next((x["prices"] for x in chain if x["option"]["type"] == side and float(x["option"]["strike"]) == atm), None)
                print(f"      {side}: courier IV {c.get('impliedVolatility') if c else None} mid {_mid(c.get('bid'), c.get('ask')) if c else None} | "
                      f"Intrinio IV {i.get('implied_volatility') if i else None} mid {_mid(i.get('close_bid'), i.get('close_ask'), i.get('mark')) if i else None}")


async def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("prices", "chains"):
        print(__doc__)
        return 2
    from_stored = "--from-stored" in argv
    client = None if from_stored and argv[0] == "prices" else IntrinioClient()
    try:
        if argv[0] == "prices":
            if argv[1] == "ALL":
                async with ScriptSessionLocal() as s:
                    symbols = list((await s.execute(text("select symbol from tickers where is_active order by symbol"))).scalars().all())
            else:
                symbols = [x.strip().upper() for x in argv[1].split(",") if x.strip()]
            out = await prices(symbols, client, date.today())
            print_prices(out, client.request_count if client else 0, client.log.retries if client else 0)
            if from_stored:
                print("  bars: price_bars_shadow (stored nightly from Intrinio by security record id), adjusted from the stored factors")
        else:
            targets = {}
            for part in argv[1].split(","):
                sym, _, q = part.partition("=")
                targets[sym.strip().upper()] = float(q) if q else None
            await chains(targets, client)
            print(f"\nrequests {client.request_count}")
    finally:
        if client is not None:
            await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
