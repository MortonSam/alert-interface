"""Ivy v3 research check (report only): the short-premium family two more ways, hold to expiration settled at the expiration close
with no exit cost, and mid-to-mid with no spread cost (an upper bound), plus the liquidity of the strikes used (bid-ask as a share
of mid). Appends its tables to ops/ivy_v3/check.md."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import text

from app.scripts import ivy_v3_analyze as A
from app.services import price_bars

OUT = Path("/app/ops/ivy_v3/check.md")


def expiry_closes(events: list[dict]) -> dict[tuple[str, str], float]:
    pairs = sorted({(e["symbol"], e["expiration"]) for e in events})
    syms = sorted({s for s, _ in pairs})
    out = {}
    with price_bars._engine().connect() as conn:
        rows = conn.execute(text("SELECT symbol, date, close FROM price_bars_shadow WHERE symbol = ANY(:s) AND date >= '2022-01-01'"), {"s": syms}).all()
    closes = {(r[0], r[1].isoformat()): float(r[2]) for r in rows if r[2] is not None}
    for s, x in pairs:
        if (s, x) in closes:
            out[(s, x)] = closes[(s, x)]
    return out


def legs_for(ev, v):
    w = v["wing"]
    if v["structure"] == "iron_butterfly":
        return [("atm", "call", "sell"), ("atm", "put", "sell"), (f"k+{w:g}", "call", "buy"), (f"k-{w:g}", "put", "buy")]
    return [("k+1", "call", "sell"), ("k-1", "put", "sell"), ("k+2", "call", "buy"), ("k-2", "put", "buy")]


def entry(ev, legs, c):
    """(credit at cost c, max loss, strikes) or None."""
    credit, strikes = 0.0, {}
    for name, kind, side in legs:
        L = ev["ladder"].get(name)
        if not L or L["strike"] is None:
            return None
        px = A.fill(L[f"pre_{kind}"], side, c)
        if px is None:
            return None
        credit += px if side == "sell" else -px
        strikes[(name, kind)] = L["strike"]
    sc, sp = strikes[(legs[0][0], "call")], strikes[(legs[1][0], "put")]
    lc, lp = strikes[(legs[2][0], "call")], strikes[(legs[3][0], "put")]
    if not (lc > sc >= sp > lp) or (v_is_condor(legs) and sc == sp):
        return None
    width = min(lc - sc, sp - lp)
    risk = width - credit
    if credit <= 0 or risk < A.MIN_RISK_SHARE * width:
        return None
    return credit, risk, (sp, sc, lp, lc)


def v_is_condor(legs):
    return legs[0][0] != "atm"


def payoff_at(spot, strikes):
    sp, sc, lp, lc = strikes
    short = max(0.0, spot - sc) + max(0.0, sp - spot)
    long = max(0.0, spot - lc) + max(0.0, lp - spot)
    return short - long         # what the short structure pays out (a cost to the seller)


def run():
    events = A.load_events()
    odds = A.Odds(A.load_reactions())
    for e in events:
        e["d"] = date.fromisoformat(e["event_date"]); e["tau"] = odds.tau(e["symbol"], e["d"])
    events.sort(key=lambda e: e["d"])
    test = [e for e in events if e["d"].year in A.TEST_YEARS]
    yrs = A.years_in(events, A.TEST_YEARS)
    xcl = expiry_closes(test)
    lines = ["## Research check: short premium two more ways (held-out 2024-2026)", "",
             "| structure | θ | wing | mode | n | EV/$100 | 95% CI | win | median spread/mid of legs |", "|---|---|---|---|---|---|---|---|---|"]
    for v in A.GRID["a_short_premium"]:
        legs = legs_for(None, v) if False else None
        for mode in ("expiry_no_exit_cost", "mid_to_mid"):
            trades, liq = [], []
            for ev in test:
                if not ev["tau"] or ev["implied_move"] / ev["tau"] <= v["theta"]:
                    continue
                legs = legs_for(ev, v)
                c = 0.5 if mode == "expiry_no_exit_cost" else 0.0
                en = entry(ev, legs, c)
                if en is None:
                    continue
                credit, risk, strikes = en
                if mode == "expiry_no_exit_cost":
                    sx = xcl.get((ev["symbol"], ev["expiration"]))
                    if sx is None:
                        continue
                    pnl = credit - payoff_at(sx, strikes)
                else:
                    r = A.structure_pnl(ev, legs, 0.0)
                    if r is None:
                        continue
                    pnl = r["pnl"]
                trades.append({"risk": risk, "pnl": pnl, "p": None})
                for name, kind, _ in legs:
                    q = ev["ladder"][name][f"pre_{kind}"]
                    m = A.mid(q) if hasattr(A, "mid") else None
                    if q and q.get("bid") is not None and q.get("ask") and q["ask"] > 0:
                        mm = (q["bid"] + q["ask"]) / 2
                        if mm > 0:
                            liq.append((q["ask"] - q["bid"]) / mm)
            m = A.metrics(trades, yrs)
            lines.append(f"| {v['structure']} | {v['theta']} | {v.get('wing', 2)} | {mode} | {m.get('n', 0)} | {m.get('ev')} | {m.get('ci')} | {m.get('win_rate')} | {round(float(np.median(liq)), 3) if liq else None} |")
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    run()
