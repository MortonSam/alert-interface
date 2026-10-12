"""Ivy v3 research check: the pricing desk's version-2 verdict on the 2024-2026 held-out events, against what the verdict structure
actually made held to expiration at the real bid and ask. Reads the research events and the local database; writes
ops/ivy_v3/verdict_check.md. The desk's "possible edge" verdict is earned only when the possible-edge group's realized interval
sits above zero (services/pricing_desk.POSSIBLE_EDGE_EARNED)."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import numpy as np

from app.database import ScriptSessionLocal
from app.scripts import ivy_v3_analyze as A
from app.scripts import ivy_v3_check as C
from app.scripts.pricing_desk import load_odds
from app.services import pricing_desk as P

OUT = Path("/app/ops/ivy_v3/verdict_check.md")


def quotes_from_ladder(ev: dict) -> dict[float, dict]:
    """{strike: {"call": {bid, ask}, "put": {bid, ask}}} from the event's pre-report ladder, as the desk reads a chain."""
    out: dict[float, dict] = {}
    for L in ev["ladder"].values():
        k = L.get("strike")
        if k is None:
            continue
        row = out.setdefault(float(k), {})
        for kind in ("call", "put"):
            q = L.get(f"pre_{kind}")
            if q and q.get("bid") is not None and q.get("ask") is not None:
                row[kind] = {"bid": q["bid"], "ask": q["ask"]}
    return {k: v for k, v in out.items() if "call" in v and "put" in v}


def realized(legs: list[dict], final_spot: float, c: float = 0.5) -> tuple[float, float] | None:
    cost = P.entry_cost(legs, c)
    if cost is None:
        return None
    return cost, P.payoff(legs, final_spot) - cost


def summary(vals: list[float]) -> dict:
    a = np.array(vals)
    if not len(a):
        return {"n": 0}
    boots = np.array([A.RNG.choice(a, len(a)).mean() for _ in range(A.BOOT)])
    return {"n": int(len(a)), "mean": round(float(a.mean()), 2), "ci": [round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)], "win": round(float(np.mean(a > 0)), 3)}


async def main():
    events = A.load_events()
    async with ScriptSessionLocal() as s:
        odds = await load_odds(s)
    for e in events:
        e["d"] = date.fromisoformat(e["event_date"])
    events.sort(key=lambda e: e["d"])
    test = [e for e in events if e["d"].year in A.TEST_YEARS]
    xcl = C.expiry_closes(test)
    groups = {"possible_edge": [], "no_edge": []}
    per_structure = {}
    for ev in test:
        x = xcl.get((ev["symbol"], ev["expiration"]))
        quotes = quotes_from_ladder(ev)
        if x is None or not quotes:
            continue
        tau = odds.tau(ev["symbol"], ev["d"])
        if not tau:
            continue
        h = P.horizon_sessions(date.fromisoformat(ev["pre_session"]), date.fromisoformat(ev["expiration"]))
        z = odds.z(ev["d"], h)
        if len(z) < P.MIN_POOL:
            continue
        spot, im = ev["spot_pre"], ev["implied_move"]
        structures = {}
        for name in P.STRUCTURES:
            legs = P.structure_legs(name, quotes, spot, im, tau)
            structures[name] = (P.evaluate_structure(name, legs, spot, tau, z), legs) if legs else None
        priced = {n: s[0] for n, s in structures.items() if s and s[0]}
        if not priced:
            continue
        verdict, which = P.verdict_for(priced)
        if verdict == P.VERDICT_POSSIBLE_EDGE:
            name = which
        else:
            name = max(priced, key=lambda n: priced[n]["ev_per_100"])           # the trade a visitor would still be tempted by
        legs = structures[name][1]
        r = realized(legs, x)
        if r is None:
            continue
        cost, pnl = r
        risk = P.max_loss(name, legs, cost)
        if not risk or risk <= 0:
            continue
        ev100 = pnl / risk * 100
        groups[verdict].append(ev100)
        per_structure.setdefault((verdict, name), []).append(ev100)
    lines = ["## Verdict check: the version-2 desk on the 2024-2026 held-out events, realized at the bid and ask, held to expiration", "",
             "| verdict | n | realized EV/$100 | 95% CI | win |", "|---|---|---|---|---|"]
    res = {}
    for g in ("possible_edge", "no_edge"):
        m = summary(groups[g]); res[g] = m
        lines.append(f"| {g} | {m.get('n', 0)} | {m.get('mean')} | {m.get('ci')} | {m.get('win')} |")
    lines += ["", "| verdict | structure | n | realized EV/$100 | 95% CI |", "|---|---|---|---|---|"]
    for (g, name), vals in sorted(per_structure.items()):
        m = summary(vals)
        lines.append(f"| {g} | {name} | {m['n']} | {m['mean']} | {m['ci']} |")
    earned = bool(res["possible_edge"].get("n") and res["possible_edge"]["ci"][0] > 0)
    lines += ["", f"Possible edge earned: {'yes' if earned else 'no'} (the possible-edge group's interval must sit above zero)."]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
