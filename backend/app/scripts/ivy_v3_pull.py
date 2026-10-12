"""Ivy v3 research (report only, never a nightly step): for every stored earnings reaction since 2022, the option chain of the
expiry that captures the report on the last session before it and the first session after it, reduced to per-event figures
(ATM straddle, implied move, a strike ladder's bids and asks, IVs) and appended to ops/ivy_v3/events.jsonl. Resumable: events
already in the file are skipped. Reads the local database and Intrinio; writes nothing to any database.

    python -m app.scripts.ivy_v3_pull                      # all events since START
    python -m app.scripts.ivy_v3_pull --symbols=TSLA,JPM   # a few tickers
    python -m app.scripts.ivy_v3_pull --shard=0/4          # one of four parallel pulls (by symbol), each to its own file
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.chain_shadow import counts_for_report
from app.services.intrinio_client import IntrinioClient
from app.services.trading_calendar import is_trading_day, last_session_before

START = date(2022, 1, 1)                 # Intrinio's EOD chains begin in 2022 on this plan (2021 returns no expirations)
OUT = Path("/app/ops/ivy_v3/events.jsonl")
K_LADDER = (-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0)      # strikes at spot × (1 + k × implied move)
P_LADDER = (-0.15, -0.10, -0.075, -0.05, -0.025, 0.025, 0.05, 0.075, 0.10, 0.15)   # strikes at spot × (1 + p)


def next_session(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def sessions(event_date: date, timing: str | None) -> tuple[date, date]:
    """(the last session before the report, the first session after it): a before-open report moves on its own day."""
    if (timing or "").lower() == "bmo":
        return last_session_before(event_date), event_date
    return event_date, next_session(event_date)           # after the close, or unknown (treated as after the close, as Ivy does)


def quotes_by(chain: list[dict], symbol: str) -> dict:
    """{(type, strike): {bid, ask, iv}} for standard contracts (the root is the symbol, not an adjusted root)."""
    out = {}
    root = symbol.replace(".", "").replace("-", "").upper()
    for r in chain:
        o, p = r.get("option") or {}, r.get("prices") or {}
        tk = (o.get("ticker") or "").replace(".", "").replace("-", "").upper()
        if tk and tk != root:
            continue
        try:
            k = float(o.get("strike"))
        except (TypeError, ValueError):
            continue
        out[(o.get("type"), k)] = {"bid": p.get("close_bid"), "ask": p.get("close_ask"), "iv": p.get("implied_volatility"), "close": p.get("close")}
    return out


def mid(q: dict | None) -> float | None:
    if not q or q.get("bid") is None or q.get("ask") is None or q["ask"] <= 0 or q["bid"] < 0:
        return None
    return (q["bid"] + q["ask"]) / 2


def nearest(strikes: list[float], target: float) -> float | None:
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


def reduce_event(symbol: str, spot_pre: float, spot_post: float, pre: dict, post: dict) -> dict | None:
    """The per-event figures from the two chains."""
    strikes = sorted({k for (t, k) in pre if ("call", k) in pre and ("put", k) in pre})
    if not strikes:
        return None
    atm = nearest(strikes, spot_pre)
    c, p = pre.get(("call", atm)), pre.get(("put", atm))
    cm, pm = mid(c), mid(p)
    if cm is None or pm is None or cm + pm <= 0:
        return None
    straddle = cm + pm
    im = straddle / spot_pre
    ladder = {}
    targets = {f"k{k:+g}": spot_pre * (1 + k * im) for k in K_LADDER}
    targets.update({f"p{p:+g}": spot_pre * (1 + p) for p in P_LADDER})
    targets["atm"] = spot_pre
    for name, target in targets.items():
        k = nearest(strikes, target)
        ladder[name] = {"strike": k, "pre_call": pre.get(("call", k)), "pre_put": pre.get(("put", k)), "post_call": post.get(("call", k)), "post_put": post.get(("put", k))}
    return {"atm_strike": atm, "straddle_bid_pre": (c["bid"] or 0) + (p["bid"] or 0), "straddle_ask_pre": (c["ask"] or 0) + (p["ask"] or 0), "straddle_mid_pre": straddle,
            "implied_move": im, "atm_iv_pre": c.get("iv"), "atm_iv_post": (post.get(("call", atm)) or {}).get("iv"),
            "strikes_n": len(strikes), "ladder": ladder}


async def events(only: set[str] | None):
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT t.symbol, t.sector, hr.event_date, hr.report_timing, hr.close_before, hr.close_after, hr.pct_change_1d, hr.pct_change_5d,
                   sr.intrinio_ticker
            FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
            LEFT JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current'
            WHERE hr.event_type = 'earnings' AND hr.event_date >= :start AND hr.pct_change_1d IS NOT NULL
            ORDER BY hr.event_date, t.symbol"""), {"start": START})).mappings().all()
    return [dict(r) for r in rows if not only or r["symbol"] in only]


async def closes_for(symbols: list[str], start: date) -> dict[str, dict[date, float]]:
    """Raw closes (the price the strikes are quoted against) per symbol and session, one query."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT symbol, date, close FROM price_bars_shadow WHERE date >= :a AND symbol = ANY(:s)"), {"a": start - timedelta(days=10), "s": symbols})).all()
    out: dict[str, dict[date, float]] = {}
    for sym, d, c in rows:
        if c is not None:
            out.setdefault(sym, {})[d] = float(c)
    return out


def forward_close(closes: dict[date, float], start: date, n: int) -> float | None:
    """The close n sessions after `start` (by the stored sessions for the symbol)."""
    days = sorted(d for d in closes if d > start)
    return closes[days[n - 1]] if len(days) >= n else None


async def main(argv: list[str]) -> int:
    global OUT
    only = {x.strip().upper() for x in next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "").split(",") if x.strip()} or None
    evs = await events(only)
    shard = next((a.split("=", 1)[1] for a in argv if a.startswith("--shard=")), None)
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        evs = [e for e in evs if sum(map(ord, e["symbol"])) % n == i]
        OUT = OUT.with_name(f"events.shard{i}.jsonl")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                d = json.loads(line); done.add((d["symbol"], d["event_date"]))
            except Exception:
                pass
    todo = [e for e in evs if (e["symbol"], e["event_date"].isoformat()) not in done]
    print(f"events {len(evs)}, done {len(done)}, to do {len(todo)}", flush=True)
    closes = await closes_for(sorted({e["symbol"] for e in todo}), START)
    client = IntrinioClient()
    t0, written, skipped = time.time(), 0, {}
    try:
        with OUT.open("a") as fh:
            for i, e in enumerate(todo):
                sym, ed, timing = e["symbol"], e["event_date"], e["report_timing"]
                rec = {"symbol": sym, "sector": e["sector"], "event_date": ed.isoformat(), "timing": timing, "pct_change_1d": float(e["pct_change_1d"]) if e["pct_change_1d"] is not None else None,
                       "pct_change_5d": float(e["pct_change_5d"]) if e["pct_change_5d"] is not None else None}
                try:
                    pre_d, post_d = sessions(ed, timing)
                    cl = closes.get(sym, {})
                    spot_pre, spot_post = cl.get(pre_d), cl.get(post_d)
                    if spot_pre is None or spot_post is None:
                        rec["skip"] = "no stored close for the pre or post session"
                    else:
                        tk = e["intrinio_ticker"] or sym
                        exps = await client.options_expirations_eod(tk, after=pre_d, before=pre_d + timedelta(days=45))
                        exp = next((x for x in exps if counts_for_report(x, ed.isoformat(), timing)), None)
                        if exp is None:
                            rec["skip"] = "no expiry listed that captures the report" if exps else "no expirations returned"
                        else:
                            pre = quotes_by(await client.options_chain_eod(tk, exp, pre_d), sym)
                            post = quotes_by(await client.options_chain_eod(tk, exp, post_d), sym)
                            red = reduce_event(sym, spot_pre, spot_post, pre, post)
                            if red is None:
                                rec["skip"] = "no priced ATM pair on the pre session"
                            else:
                                rec.update({"pre_session": pre_d.isoformat(), "post_session": post_d.isoformat(), "expiration": exp, "spot_pre": spot_pre, "spot_post": spot_post,
                                            "close_20d": forward_close(cl, post_d, 20), "close_5d": forward_close(cl, post_d, 5), **red})
                except Exception as exc:
                    rec["skip"] = f"error: {str(exc)[:120]}"
                if rec.get("skip"):
                    skipped[rec["skip"][:40]] = skipped.get(rec["skip"][:40], 0) + 1
                fh.write(json.dumps(rec) + "\n"); fh.flush()
                written += 1
                if i % 100 == 0:
                    print(f"{i}/{len(todo)} {sym} {ed} requests {client.request_count} {time.time() - t0:.0f}s skipped {skipped}", flush=True)
    finally:
        await client.close()
    print(f"done: wrote {written}, requests {client.request_count}, {time.time() - t0:.0f}s, skipped {skipped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
