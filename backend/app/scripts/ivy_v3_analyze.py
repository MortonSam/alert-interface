"""Ivy v3 research (report only): every setup family on real historical option prices. Reads ops/ivy_v3/events.jsonl
(app.scripts.ivy_v3_pull), the local earnings_features and historical_reactions tables, and the stored bars. Writes
ops/ivy_v3/results.json and the report ops/ivy_v3_research.md. Never touches production or Ivy's live rule.

Pre-registered: fit years 2022-2023, held-out 2024-2026; costs at mid ± half the spread (c=0.5) and mid ± the full spread (c=1.0);
odds from the stock's own prior reports shrunk toward its sector with weight SHRINK_K; a variant passes only when its held-out
expected value's bootstrap 95% interval stays above zero at c=0.5 and the point estimate stays positive at c=1.0, over at least
MIN_TRADES held-out trades.
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text


from app.services import price_bars

EVENTS = Path("/app/ops/ivy_v3/events.jsonl")
OUT_JSON = Path("/app/ops/ivy_v3/results.json")
REPORT = Path("/app/ops/ivy_v3_research.md")
FIT_YEARS, TEST_YEARS = (2022, 2023), (2024, 2025, 2026)
SHRINK_K = 6                  # a stock with n prior reports gets weight n against the sector's K
MIN_PRIOR = 2                 # fewer own reports than this: the sector alone
COSTS = (0.5, 1.0)            # c: a buy fills at mid + c*spread, a sell at mid - c*spread
STOCK_COST_BPS = {0.5: 10, 1.0: 20}      # round trip, for the stock families
BOOT = 2000
MIN_RISK_SHARE = 0.25         # a short-premium structure must keep at least this share of its width at risk
MIN_TRADES = 30               # a held-out verdict needs at least this many trades; fewer is "not enough evidence", never a pass
RNG = np.random.default_rng(7)
GRID = {
    "a_short_premium": [{"structure": s, "theta": th, "wing": w} for s in ("iron_butterfly", "iron_condor") for th in (1.1, 1.25, 1.5, 1.75, 2.0) for w in ((1, 2) if s == "iron_butterfly" else (2,))],
    "b_long_vol": [{"structure": s, "theta": th} for s in ("straddle", "strangle") for th in (0.5, 0.65, 0.8, 0.9)],
    "c_v2_baseline": [{"momentum": m, "vol_cap": v} for m in (-0.10, -0.05) for v in (1.2, 1.5)],
    "d_post_earnings_drift": [{"theta_tau": t} for t in (1.0, 1.5, 2.0)] + [{"theta_abs": a} for a in (0.05, 0.08)],
    "e_analyst_drift": [{"action": a} for a in ("up", "down", "both")],
}


# ── data ──────────────────────────────────────────────────────────────────────

def event_lines():
    """Every pulled record, from the single file and the shard files, one per (symbol, date)."""
    seen = set()
    for path in sorted(EVENTS.parent.glob("events*.jsonl")):
        for line in path.open():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            key = (d.get("symbol"), d.get("event_date"))
            if key in seen:
                continue
            seen.add(key)
            yield d


def load_events() -> list[dict]:
    return [d for d in event_lines() if not d.get("skip")]


def db_rows(sql: str, params: dict | None = None):
    with price_bars._engine().connect() as conn:
        return conn.execute(text(sql), params or {}).mappings().all()


def load_reactions():
    return [dict(r) for r in db_rows("""SELECT t.symbol, t.sector, hr.event_date, hr.pct_change_1d, hr.pct_change_5d FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id WHERE hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL ORDER BY hr.event_date""")]


def load_features():
    return {(r["symbol"], r["event_date"].isoformat()): dict(r) for r in db_rows(
        "SELECT symbol, event_date, momentum_20d, prior_avg_abs_1d, prior_avg_abs_5d, prior_n FROM earnings_features")}


def load_analyst_actions():
    return [dict(r) for r in db_rows("""SELECT t.symbol, hr.event_date, e.metadata->>'action' AS action, hr.pct_change_1d, e.metadata->>'firm' AS firm,
        e.metadata->>'from_grade' AS from_grade, e.metadata->>'to_grade' AS to_grade, e.metadata->>'price_target' AS price_target FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id JOIN events e ON e.id = hr.event_id WHERE hr.event_type = 'analyst_action' AND hr.event_date >= '2022-01-01' ORDER BY hr.event_date""")]


# ── odds: the stock's own prior reports, shrunk toward its sector, no look-ahead ──

class Odds:
    """Expanding-window statistics: for an event on date d, only reports dated before d count."""

    def __init__(self, reactions: list[dict]):
        self.by_stock: dict[str, list[tuple[date, float]]] = defaultdict(list)
        self.by_sector: dict[str, list[tuple[date, float]]] = defaultdict(list)
        self.pool: list[tuple[date, float]] = []          # standardized moves z = move / tau, for the probability model
        self.sector_of: dict[str, str] = {}
        for r in reactions:
            sym, d, m = r["symbol"], r["event_date"], float(r["pct_change_1d"]) / 100
            self.sector_of[sym] = r["sector"] or "Unknown"
            self.by_stock[sym].append((d, m))
            self.by_sector[self.sector_of[sym]].append((d, m))
        for r in reactions:                                # build the z pool in date order with the tau known at the time
            sym, d, m = r["symbol"], r["event_date"], float(r["pct_change_1d"]) / 100
            tau = self.tau(sym, d)
            if tau:
                self.pool.append((d, m / tau))
        self.pool.sort()

    @staticmethod
    def _before(series: list[tuple[date, float]], d: date) -> list[float]:
        i = bisect_left(series, (d, -1e9))
        return [m for _, m in series[:i]]

    def tau(self, sym: str, d: date) -> float | None:
        """The stock's typical absolute 1-day move: own prior reports, shrunk toward the sector's."""
        own = [abs(m) for m in self._before(self.by_stock.get(sym, []), d)]
        sect = [abs(m) for m in self._before(self.by_sector.get(self.sector_of.get(sym, "Unknown"), []), d)]
        if len(sect) < 20:
            return None
        ms = float(np.mean(sect))
        if len(own) < MIN_PRIOR:
            return ms
        n = len(own)
        return (n * float(np.mean(own)) + SHRINK_K * ms) / (n + SHRINK_K)

    def prob(self, d: date, kind: str, x: float) -> float | None:
        """P(|z| < x) ('inside'), P(|z| > x) ('outside'), P(z > x) ('above'), from the pooled standardized moves before d."""
        i = bisect_left(self.pool, (d, -1e9))
        z = np.array([v for _, v in self.pool[:i]])
        if len(z) < 200:
            return None
        if kind == "inside":
            return float(np.mean(np.abs(z) < x))
        if kind == "outside":
            return float(np.mean(np.abs(z) > x))
        return float(np.mean(z > x))


# ── pricing helpers ───────────────────────────────────────────────────────────

def fill(q: dict | None, side: str, c: float, intrinsic: float | None = None) -> float | None:
    """The price a leg fills at: buy at mid + c*spread, sell at mid - c*spread (never below 0). Without a two-sided quote,
    the intrinsic value when given (an expiry-day close), else None."""
    if q and q.get("bid") is not None and q.get("ask") is not None and q["ask"] > 0 and q["bid"] >= 0:
        m, s = (q["bid"] + q["ask"]) / 2, q["ask"] - q["bid"]
        return m + c * s if side == "buy" else max(0.0, m - c * s)
    return intrinsic


def intrinsic(kind: str, strike: float, spot: float) -> float:
    return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)


def leg_pnl(ev: dict, name: str, kind: str, side: str, c: float) -> tuple[float, float] | None:
    """(entry price paid or received, exit price) for one leg: entry on the pre chain, exit on the post chain (intrinsic at expiry)."""
    L = ev["ladder"].get(name)
    if not L or L["strike"] is None:
        return None
    pre, post = L[f"pre_{kind}"], L[f"post_{kind}"]
    e = fill(pre, side, c)
    at_expiry = ev["expiration"] == ev["post_session"]
    x = fill(post, "sell" if side == "buy" else "buy", c, intrinsic(kind, L["strike"], ev["spot_post"]) if at_expiry else None)
    if e is None or x is None:
        return None
    return e, x


def structure_pnl(ev: dict, legs: list[tuple[str, str, str]], c: float) -> dict | None:
    """legs: (ladder name, kind, side). Returns {debit (net paid, negative for a credit), exit_value, pnl, strikes}."""
    paid = received = 0.0
    strikes = {}
    for name, kind, side in legs:
        r = leg_pnl(ev, name, kind, side, c)
        if r is None:
            return None
        e, x = r
        strikes[(name, kind)] = ev["ladder"][name]["strike"]
        if side == "buy":
            paid += e; received += x
        else:
            received += e; paid += x
    return {"net_entry": None, "pnl": received - paid, "strikes": strikes}


# ── the families ──────────────────────────────────────────────────────────────

def trade_a(ev: dict, odds: Odds, v: dict, c: float):
    tau = ev["tau"]
    if not tau or ev["implied_move"] / tau <= v["theta"]:
        return None
    w = v["wing"]
    if v["structure"] == "iron_butterfly":
        legs = [("atm", "call", "sell"), ("atm", "put", "sell"), (f"k+{w:g}", "call", "buy"), (f"k-{w:g}", "put", "buy")]
    else:
        legs = [("k+1", "call", "sell"), ("k-1", "put", "sell"), ("k+2", "call", "buy"), ("k-2", "put", "buy")]
    r = structure_pnl(ev, legs, c)
    if r is None:
        return None
    k = r["strikes"]
    short_c, short_p = k[(legs[0][0], "call")], k[(legs[1][0], "put")]
    long_c, long_p = k[(legs[2][0], "call")], k[(legs[3][0], "put")]
    if not (long_c > short_c >= short_p > long_p) or (v["structure"] == "iron_condor" and short_c == short_p):
        return None
    credit = sum(fill(ev["ladder"][n][f"pre_{kd}"], "sell", c) for n, kd, _ in legs[:2]) - sum(fill(ev["ladder"][n][f"pre_{kd}"], "buy", c) for n, kd, _ in legs[2:])
    width = min(long_c - short_c, short_p - long_p)
    risk = width - credit
    if credit <= 0 or risk < MIN_RISK_SHARE * width:
        return None                      # a wing inside the credit leaves almost nothing at risk: dollars per $100 risked would mean nothing
    be = (credit + (short_c - short_p) / 2) / ev["spot_pre"]       # the move that reaches breakeven (half the short gap plus the credit)
    return {"risk": risk, "pnl": r["pnl"], "p": odds.prob(ev["d"], "inside", be / tau), "detail": {"credit": credit, "width": width, "short": (short_p, short_c), "long": (long_p, long_c)}}


def trade_b(ev: dict, odds: Odds, v: dict, c: float):
    tau = ev["tau"]
    if not tau or ev["implied_move"] / tau >= v["theta"]:
        return None
    legs = [("atm", "call", "buy"), ("atm", "put", "buy")] if v["structure"] == "straddle" else [("k+1", "call", "buy"), ("k-1", "put", "buy")]
    r = structure_pnl(ev, legs, c)
    if r is None:
        return None
    debit = sum(fill(ev["ladder"][n][f"pre_{kd}"], "buy", c) for n, kd, _ in legs)
    if debit <= 0:
        return None
    kc, kp = r["strikes"][(legs[0][0], "call")], r["strikes"][(legs[1][0], "put")]
    be = (debit + (kc - kp) / 2) / ev["spot_pre"]
    return {"risk": debit, "pnl": r["pnl"], "p": odds.prob(ev["d"], "outside", be / tau), "detail": {"debit": debit, "strikes": (kp, kc)}}


def trade_c(ev: dict, odds: Odds, v: dict, c: float):
    f = ev.get("feat") or {}
    mom, n, usual5 = f.get("momentum_20d"), f.get("prior_n"), f.get("prior_avg_abs_5d")
    if mom is None or n is None or usual5 is None or n < 8 or float(mom) > v["momentum"] * 100:      # momentum_20d is stored in percent
        return None
    usual = float(usual5) / 100
    if ev["implied_move"] > v["vol_cap"] * usual:
        return None
    target = ev["spot_pre"] * (1 + usual)
    cands = [(name, L["strike"]) for name, L in ev["ladder"].items() if L["strike"] and L["strike"] > ev["ladder"]["atm"]["strike"]]
    if not cands:
        return None
    short_name = min(cands, key=lambda x: abs(x[1] - target))[0]
    r = structure_pnl(ev, [("atm", "call", "buy"), (short_name, "call", "sell")], c)
    if r is None:
        return None
    debit = fill(ev["ladder"]["atm"]["pre_call"], "buy", c) - fill(ev["ladder"][short_name]["pre_call"], "sell", c)
    if debit <= 0:
        return None
    tau = ev["tau"]
    be = (ev["ladder"]["atm"]["strike"] + debit) / ev["spot_pre"] - 1
    return {"risk": debit, "pnl": r["pnl"], "p": odds.prob(ev["d"], "above", be / tau) if tau else None, "stock_5d": ev.get("pct_change_5d"),
            "detail": {"debit": debit, "long": ev["ladder"]["atm"]["strike"], "short": ev["ladder"][short_name]["strike"]}}


SPY: dict[date, float] = {}       # the index's closes, for market-relative 20-day returns (d and e)


def spy_ret(start: date, n: int = 20) -> float | None:
    ds = sorted(d for d in SPY if d >= start)
    return SPY[ds[n]] / SPY[ds[0]] - 1 if len(ds) > n else None


def trade_d(ev: dict, odds: Odds, v: dict, c: float, hist: dict):
    move = ev["pct_change_1d"] / 100
    tau = ev["tau"]
    if "theta_tau" in v:
        if not tau or abs(move) < v["theta_tau"] * tau:
            return None
    elif abs(move) < v["theta_abs"]:
        return None
    if ev.get("close_20d") is None:
        return None
    mkt = spy_ret(date.fromisoformat(ev["post_session"]))
    if mkt is None:
        return None
    ret = np.sign(move) * (ev["close_20d"] / ev["spot_post"] - 1 - mkt) - STOCK_COST_BPS[c] / 1e4      # beyond the index's own 20-day move
    key = json.dumps(v, sort_keys=True)
    p = hist.get(key)
    return {"risk": 1.0, "pnl": ret, "p": p, "detail": {"move_1d": move, "direction": "long" if move > 0 else "short"}}


# ── evaluation ────────────────────────────────────────────────────────────────

def metrics(trades: list[dict], years: float) -> dict:
    if not trades:
        return {"n": 0}
    ev = np.array([t["pnl"] / t["risk"] * 100 for t in trades])
    boots = np.array([RNG.choice(ev, len(ev)).mean() for _ in range(BOOT)]) if len(ev) > 1 else ev
    wins, losses = ev[ev > 0], ev[ev <= 0]
    cum = np.cumsum(ev)
    dd = float(np.max(np.maximum.accumulate(cum) - cum)) if len(cum) else 0.0
    out = {"n": int(len(ev)), "per_year": round(len(ev) / years, 1), "ev": round(float(ev.mean()), 2), "ci": [round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)],
           "win_rate": round(float(np.mean(ev > 0)), 3), "avg_win": round(float(wins.mean()), 2) if len(wins) else None, "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
           "worst": round(float(ev.min()), 2), "max_drawdown": round(dd, 1)}
    bands = defaultdict(list)
    for t, e in zip(trades, ev):
        if t.get("p") is not None:
            lo = min(int(t["p"] * 5) / 5, 0.8)
            bands[f"{lo:.1f}-{lo + 0.2:.1f}"].append(e > 0)
    out["calibration"] = {b: {"n": len(v), "stated": b, "realized": round(float(np.mean(v)), 2)} for b, v in sorted(bands.items())}
    return out


def years_in(events: list[dict], yrs) -> float:
    ds = [e["d"] for e in events if e["d"].year in yrs]
    return max((max(ds) - min(ds)).days / 365.25, 0.5) if ds else 1.0


def run():
    events = load_events()
    odds = Odds(load_reactions())
    feats = load_features()
    for e in events:
        e["d"] = date.fromisoformat(e["event_date"])
        e["tau"] = odds.tau(e["symbol"], e["d"])
        e["feat"] = feats.get((e["symbol"], e["event_date"]))
    events.sort(key=lambda e: e["d"])
    fit = [e for e in events if e["d"].year in FIT_YEARS]
    test = [e for e in events if e["d"].year in TEST_YEARS]
    yrs = {"fit": years_in(events, FIT_YEARS), "test": years_in(events, TEST_YEARS)}
    results = []
    spy_df0 = price_bars.bulk_bars_sync(["SPY"], date(2021, 12, 1)).get("SPY")
    if spy_df0 is not None:
        SPY.update({t.date(): float(c) for t, c in zip(spy_df0.index, spy_df0["Close"])})
    families = {"a_short_premium": trade_a, "b_long_vol": trade_b, "c_v2_baseline": trade_c}
    for fam, fn in families.items():
        for v in GRID[fam]:
            row = {"family": fam, "variant": v}
            for c in COSTS:
                for split, evs in (("fit", fit), ("test", test)):
                    trades = []
                    for e in evs:
                        t = fn(e, odds, v, c)
                        if t:
                            t["symbol"], t["date"] = e["symbol"], e["event_date"]; trades.append(t)
                    row[f"{split}_c{c}"] = metrics(trades, yrs[split])
                    if fam == "c_v2_baseline" and c == 0.5:
                        s5 = [t["stock_5d"] for t in trades if t.get("stock_5d") is not None]
                        row[f"{split}_stock_5d"] = {"n": len(s5), "up_rate": round(float(np.mean([x > 0 for x in s5])), 3) if s5 else None, "mean_pct": round(float(np.mean(s5)), 2) if s5 else None}
                    if split == "test" and c == 0.5:
                        row["test_trades"] = trades
            results.append(row)
    # d: post-earnings drift, the stated probability is the variant's own expanding hit rate (no option odds apply)
    for v in GRID["d_post_earnings_drift"]:
        row = {"family": "d_post_earnings_drift", "variant": v}
        for c in COSTS:
            hits: list[bool] = []
            for split, evs in (("fit", fit), ("test", test)):
                trades = []
                for e in evs:
                    p = float(np.mean(hits)) if len(hits) >= 30 else None
                    t = trade_d(e, odds, v, c, {json.dumps(v, sort_keys=True): p})
                    if t:
                        t["symbol"], t["date"] = e["symbol"], e["event_date"]; trades.append(t); hits.append(t["pnl"] > 0)
                row[f"{split}_c{c}"] = metrics(trades, yrs[split])
                if split == "test" and c == 0.5:
                    row["test_trades"] = trades
        results.append(row)
    # e: analyst-action drift, research only (the actions come from an unlicensed source)
    acts = load_analyst_actions()
    syms = sorted({a["symbol"] for a in acts})
    spy_df = price_bars.bulk_bars_sync(["SPY"], date(2021, 12, 1)).get("SPY")
    if spy_df is not None:
        SPY.update({t.date(): float(c) for t, c in zip(spy_df.index, spy_df["Close"])})
    bars = price_bars.bulk_bars_sync(syms, date(2021, 12, 1))
    closes = {s: ([t.date() for t in df.index], df["Close"].tolist()) for s, df in bars.items()} if bars else {}
    def ret20(sym, d):
        """(excess 20-session return over the index, the entry close, the exit close, the index's own return) from the action day's close."""
        if sym not in closes:
            return None
        ds, cs = closes[sym]
        i = bisect_left(ds, d)
        if i >= len(ds) or i + 20 >= len(ds):
            return None
        start = i                            # the action day's close (or the next session's)
        mkt = spy_ret(ds[start])
        return None if mkt is None else (cs[start + 20] / cs[start] - 1 - mkt, cs[start], cs[start + 20], mkt, ds[start], ds[start + 20])
    for v in GRID["e_analyst_drift"]:
        row = {"family": "e_analyst_drift", "variant": v, "unshippable": "analyst actions come from Yahoo, an unlicensed source"}
        for c in COSTS:
            hits: list[bool] = []
            evs_so_far: list[float] = []
            for split, years_ in (("fit", FIT_YEARS), ("test", TEST_YEARS)):
                trades = []
                for a in acts:
                    if a["event_date"].year not in years_ or (v["action"] != "both" and a["action"] != v["action"]):
                        continue
                    r = ret20(a["symbol"], a["event_date"])
                    if r is None:
                        continue
                    excess, entry, exit_, mkt, d_in, d_out = r
                    sign = 1 if a["action"] == "up" else -1
                    pnl = sign * excess - STOCK_COST_BPS[c] / 1e4
                    p = float(np.mean(hits)) if len(hits) >= 30 else None
                    stated_ev = float(np.mean(evs_so_far)) * 100 if len(evs_so_far) >= 30 else None
                    trades.append({"risk": 1.0, "pnl": pnl, "p": p, "stated_ev": stated_ev, "symbol": a["symbol"], "date": a["event_date"].isoformat(),
                                   "detail": {"firm": a.get("firm"), "from_grade": a.get("from_grade"), "to_grade": a.get("to_grade"), "price_target": a.get("price_target"),
                                              "entry_close": entry, "exit_close": exit_, "entry_date": d_in.isoformat(), "exit_date": d_out.isoformat(), "index_20d": mkt, "excess_20d": excess,
                                              "prior_n": len(hits)}})
                    hits.append(pnl > 0); evs_so_far.append(pnl)
                row[f"{split}_c{c}"] = metrics(trades, yrs[split])
                if split == "test" and c == 0.5:
                    row["test_trades"] = trades
        results.append(row)
    for row in results:
        t5, t1 = row["test_c0.5"], row["test_c1.0"]
        row["passes"] = bool(t5.get("n", 0) >= MIN_TRADES and t5["ci"][0] > 0 and t1.get("n") and t1["ev"] > 0)
    coverage = defaultdict(int)
    for d in event_lines():
        coverage[(d["event_date"][:4], "ok" if not d.get("skip") else "skip:" + d["skip"][:40])] += 1
    OUT_JSON.write_text(json.dumps({"events": len(events), "fit_years": yrs["fit"], "test_years": yrs["test"], "coverage": {f"{y} {k}": n for (y, k), n in sorted(coverage.items())},
                                    "results": [{k: v for k, v in r.items() if k != "test_trades"} for r in results]}, indent=1, default=str))
    # the three real picks of the best passing variant (else the best held-out variant), from the held-out years
    ranked = sorted(results, key=lambda r: (-int(r["passes"]), -(r["test_c0.5"].get("ev") or -1e9)))
    best = ranked[0]
    picks = [t for t in sorted(best.get("test_trades") or [], key=lambda t: t["date"]) if t.get("p") is not None]
    cards = [picks[i] for i in (0, len(picks) // 2, len(picks) - 1)] if len(picks) >= 3 else picks     # the first, the middle and the last held-out pick
    (OUT_JSON.parent / "picks.json").write_text(json.dumps({"variant": {k: best[k] for k in ("family", "variant", "passes")}, "cards": cards}, indent=1, default=str))
    lines = ["| pass | family | variant | fit n | fit EV | held-out n | per yr | EV/$100 | 95% CI | win | avg win | avg loss | worst | max DD | EV full spread |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ranked:
        f5, t5, t1 = r["fit_c0.5"], r["test_c0.5"], r["test_c1.0"]
        lines.append(f"| {'yes' if r['passes'] else ''} | {r['family']} | {json.dumps(r['variant'])} | {f5.get('n', 0)} | {f5.get('ev')} | {t5.get('n', 0)} | {t5.get('per_year')} | {t5.get('ev')} | {t5.get('ci')} | {t5.get('win_rate')} | {t5.get('avg_win')} | {t5.get('avg_loss')} | {t5.get('worst')} | {t5.get('max_drawdown')} | {t1.get('ev')} |")
    cal = ["", "## Calibration (held-out, c=0.5): stated probability band vs realized hit rate", ""]
    for r in ranked:
        c5 = r["test_c0.5"].get("calibration") or {}
        if c5:
            cal.append(f"- {r['family']} {json.dumps(r['variant'])}: " + "; ".join(f"{b}: n={v['n']} realized {v['realized']}" for b, v in c5.items()))
    cov = ["", "## Coverage", ""] + [f"- {k}: {n}" for k, n in sorted({f"{y} {k}": n for (y, k), n in coverage.items()}.items())]
    (OUT_JSON.parent / "tables.md").write_text("\n".join(lines + cal + cov) + "\n")
    print(json.dumps({"events": len(events), "coverage": {f"{y} {k}": n for (y, k), n in sorted(coverage.items())}}, indent=0))
    for r in ranked:
        t5 = r["test_c0.5"]; f5 = r["fit_c0.5"]; t1 = r["test_c1.0"]
        print(f"{'PASS' if r['passes'] else '    '} {r['family']:22} {json.dumps(r['variant'])[:52]:52} fit ev {f5.get('ev')} n={f5.get('n')} | test ev {t5.get('ev')} ci {t5.get('ci')} n={t5.get('n')} /yr {t5.get('per_year')} win {t5.get('win_rate')} | full-spread ev {t1.get('ev')}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
