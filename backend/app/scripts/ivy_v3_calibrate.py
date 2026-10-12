"""Ivy v3 research check: does the desk's expected value (the report move taken as the move to expiry, integrated over the stock's own
1-day distribution) agree with what an iron condor at ±1 implied move actually made held to expiration? Held-out 2024-2026, entry at
the bid and ask, no exit cost. Also the same model fed the move from the pre-report close to the expiration close instead."""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date

import numpy as np

from app.scripts import ivy_v3_analyze as A
from app.scripts import ivy_v3_check as C


def pooled(events, key):
    """Standardized moves z = move / tau for every event, by date, for an expanding-window pool."""
    pool = []
    for e in events:
        if e["tau"] and e.get(key) is not None:
            pool.append((e["d"], e[key] / e["tau"]))
    pool.sort()
    return pool


def z_before(pool, d, n_min=200):
    i = bisect_left(pool, (d, -1e9))
    z = np.array([v for _, v in pool[:i]])
    return z if len(z) >= n_min else None


def model_ev(ev, strikes, credit, risk, z):
    sp, sc, lp, lc = strikes
    spots = ev["spot_pre"] * (1 + z * ev["tau"])
    payoff = np.array([C.payoff_at(s, strikes) for s in spots])
    return float(np.mean(credit - payoff)) / risk * 100


def run():
    events = A.load_events()
    odds = A.Odds(A.load_reactions())
    for e in events:
        e["d"] = date.fromisoformat(e["event_date"]); e["tau"] = odds.tau(e["symbol"], e["d"])
    events.sort(key=lambda e: e["d"])
    xcl = C.expiry_closes(events)
    for e in events:
        e["move_1d"] = e["pct_change_1d"] / 100
        x = xcl.get((e["symbol"], e["expiration"]))
        e["move_exp"] = (x / e["spot_pre"] - 1) if x else None
    pool_1d, pool_exp = pooled(events, "move_1d"), pooled(events, "move_exp")
    v = {"structure": "iron_condor", "theta": 1.1, "wing": 2}
    rows = []
    for ev in events:
        if ev["d"].year not in A.TEST_YEARS or not ev["tau"] or ev["implied_move"] / ev["tau"] <= v["theta"]:
            continue
        legs = C.legs_for(ev, v)
        en = C.entry(ev, legs, 0.5)
        x = xcl.get((ev["symbol"], ev["expiration"]))
        if en is None or x is None:
            continue
        credit, risk, strikes = en
        z1, z2 = z_before(pool_1d, ev["d"]), z_before(pool_exp, ev["d"])
        if z1 is None or z2 is None:
            continue
        rows.append({"pred_1d": model_ev(ev, strikes, credit, risk, z1), "pred_exp": model_ev(ev, strikes, credit, risk, z2),
                     "real": (credit - C.payoff_at(x, strikes)) / risk * 100})
    r = {k: np.array([x[k] for x in rows]) for k in ("pred_1d", "pred_exp", "real")}
    print(f"iron condor ±1 IM, θ>1.1, held-out, entry at bid/ask, held to expiry: n={len(rows)}")
    print(f"  model (1-day distribution, as the desk computes): mean predicted EV {r['pred_1d'].mean():+.1f} per $100; share predicted > 0 at bid/ask {np.mean(r['pred_1d'] > 0):.0%}")
    print(f"  model (move to expiration distribution):          mean predicted EV {r['pred_exp'].mean():+.1f}; share predicted > 0 {np.mean(r['pred_exp'] > 0):.0%}")
    print(f"  realized:                                          mean {r['real'].mean():+.1f} per $100")
    for name in ("pred_1d", "pred_exp"):
        pos = r[name] > 0
        print(f"  when {name} > 0 (n={pos.sum()}): realized mean {r['real'][pos].mean():+.1f}; when ≤ 0 (n={(~pos).sum()}): realized {r['real'][~pos].mean():+.1f}")
    q = np.quantile(np.abs(np.array([v for _, v in pool_1d])), [0.5, 0.9, 0.99]); q2 = np.quantile(np.abs(np.array([v for _, v in pool_exp])), [0.5, 0.9, 0.99])
    print(f"  |z| quantiles 50/90/99: 1-day {q.round(2)}; to-expiry {q2.round(2)}  (the move to expiry is the wider distribution)")


if __name__ == "__main__" and "--long-call" not in __import__("sys").argv:
    run()


def run_long_call():
    """The desk's long ATM call: predicted EV over the move-to-expiry pool (raw, and centered on zero drift) against what it made held to expiry."""
    events = A.load_events()
    odds = A.Odds(A.load_reactions())
    for e in events:
        e["d"] = date.fromisoformat(e["event_date"]); e["tau"] = odds.tau(e["symbol"], e["d"])
    events.sort(key=lambda e: e["d"])
    xcl = C.expiry_closes(events)
    for e in events:
        x = xcl.get((e["symbol"], e["expiration"]))
        e["move_exp"] = (x / e["spot_pre"] - 1) if x else None
    pool = pooled(events, "move_exp")
    rows = []
    for ev in events:
        if ev["d"].year not in A.TEST_YEARS or not ev["tau"]:
            continue
        L = ev["ladder"]["atm"]; q = L["pre_call"]; x = xcl.get((ev["symbol"], ev["expiration"]))
        if not q or q.get("bid") is None or q.get("ask") is None or q["ask"] <= 0 or x is None:
            continue
        cost = q["ask"]                                  # buy at the ask
        z = z_before(pool, ev["d"])
        if z is None:
            continue
        k = L["strike"]
        for name, zz in (("raw", z), ("centered", z - z.mean())):
            spots = ev["spot_pre"] * (1 + zz * ev["tau"])
            pred = float(np.mean(np.maximum(spots - k, 0) - cost)) / cost * 100
            rows.append((name, pred, (max(x - k, 0) - cost) / cost * 100))
    for name in ("raw", "centered"):
        r = [(p, a) for n, p, a in rows if n == name]
        pred = np.array([p for p, _ in r]); real = np.array([a for _, a in r])
        pos = pred > 0
        print(f"long ATM call, held-out, bought at the ask, held to expiry, {name} pool: n={len(r)} predicted mean {pred.mean():+.1f}, realized mean {real.mean():+.1f}; "
              f"predicted > 0 n={pos.sum()} realized {real[pos].mean():+.1f}; predicted <= 0 n={(~pos).sum()} realized {real[~pos].mean():+.1f}")


if __name__ == "__main__" and "--long-call" in __import__("sys").argv:
    run_long_call()
