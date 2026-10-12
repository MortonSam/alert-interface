"""The pricing desk (Ivy v3): for every stock about to report, what the options charge against what the stock's own history says,
and the expected value per $100 risked of the four trades a visitor would be tempted by, at the real bid and ask.

Definitions follow the v3 research (app/scripts/ivy_v3_analyze.py, ops/ivy_v3_research.md):
- typical move τ: the mean absolute 1-day report move of the stock's own prior reports, shrunk toward its sector's mean with weight
  SHRINK_K (a stock with n reports gets weight n); fewer than MIN_PRIOR own reports uses the sector alone;
- the stock's own distribution: every prior report's move over h sessions from the close before the report (h = the sessions the
  card's expiry is away from its chain date, 1 to MAX_HORIZON), standardized by the 1-day τ known at the time (z_h = move_h / τ) and
  pooled per horizon; a structure's expected payoff integrates its expiration payoff over spot × (1 + z_h τ). Version 1 used the
  1-day move for every horizon and predicted +2.8 per $100 for iron condors that made −10.8 held out (ops/ivy_v3_research.md, the
  calibration check); the move to expiry is the wider distribution, and with it the same model predicts −11.0. The pool is centered
  (its mean drift removed): the years in it rose, and a long call priced on that drift looked worth +22 per $100 at the ask;
- fills: a buy at mid + c × spread, a sell at mid − c × spread; c = 0.5 is the real bid and ask, c = 1.0 a full spread each way;
- risk: the net debit, or for the iron condor the width less the credit; expected value per $100 risked = (E[payoff] − cost) / risk × 100.

Any change to how a number here is computed bumps PRICING_COMPUTATION_VERSION so stored cards and verdict rows stay comparable.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timezone

import numpy as np

PRICING_COMPUTATION_VERSION = 2       # 2 (2026-10-12): expected payoff over the move to expiry, not the 1-day move
MAX_HORIZON = 10                      # sessions from the chain date to the expiry that the distribution is built for; further expiries use this
SHRINK_K = 6
MIN_PRIOR = 2
MIN_SECTOR = 20                 # fewer sector reports than this: no typical move
MIN_POOL = 200                  # fewer pooled standardized moves than this: no probability
PRIOR_MOVES_SHOWN = 20
REPORT_WINDOW_DAYS = 7
STRUCTURES = ("long_call", "long_straddle", "bull_call_spread", "iron_condor")
VERDICT_NO_EDGE, VERDICT_POSSIBLE_EDGE = "no_edge", "possible_edge"
EXPECTED_PAYOFF_METHOD = ("payoff at expiration averaged over prior report moves measured over the same number of sessions as this expiry is from the "
                          "chain date (each standardized by the typical 1-day move known at the time, rescaled by today's typical move, the pool's mean drift "
                          "removed), less the entry cost at the real bid and ask")
CARD_KEY = "pricing_card:{sym}"
STEP_LABEL = "Pricing desk (Ivy v3)"
# validate's bands (check_pricing_cards): a card outside them is an ERROR
BANDS = {"implied_move_pct": (0.5, 60.0), "typical_move_pct": (0.5, 40.0), "p_beyond_implied": (0.05, 0.95), "ev_per_100": (-100.0, 300.0), "horizon_sessions": (1, MAX_HORIZON)}


# ── the stock's own odds ──────────────────────────────────────────────────────

class Odds:
    """Expanding-window statistics over the stored earnings reactions: for a date d, only reports before d count."""

    def __init__(self, reactions: list[dict]):
        self.by_stock: dict[str, list[tuple[date, float]]] = defaultdict(list)
        self.by_sector: dict[str, list[tuple[date, float]]] = defaultdict(list)
        self.sector_of: dict[str, str] = {}
        self.pools: dict[int, list[tuple[date, float]]] = defaultdict(list)     # horizon h -> (date, move_h / tau)
        for r in sorted(reactions, key=lambda r: r["event_date"]):
            sym, d, m = r["symbol"], r["event_date"], float(r["pct_change_1d"]) / 100
            self.sector_of[sym] = r.get("sector") or "Unknown"
            self.by_stock[sym].append((d, m))
            self.by_sector[self.sector_of[sym]].append((d, m))
        for r in sorted(reactions, key=lambda r: r["event_date"]):
            sym, d, m = r["symbol"], r["event_date"], float(r["pct_change_1d"]) / 100
            tau = self.tau(sym, d)
            if not tau:
                continue
            self.pools[1].append((d, m / tau))
            for h, mh in (r.get("moves") or {}).items():          # {h: move over h sessions from the close before the report}, fractions
                if int(h) > 1 and mh is not None:
                    self.pools[int(h)].append((d, float(mh) / tau))
        for h in self.pools:
            self.pools[h].sort()

    @property
    def pool(self) -> list[tuple[date, float]]:
        return self.pools[1]

    @staticmethod
    def _before(series: list[tuple[date, float]], d: date) -> list[float]:
        return [m for _, m in series[: bisect_left(series, (d, -1e9))]]

    def own_moves(self, sym: str, d: date) -> list[tuple[date, float]]:
        s = self.by_stock.get(sym, [])
        return s[: bisect_left(s, (d, -1e9))]

    def tau(self, sym: str, d: date) -> float | None:
        own = [abs(m) for m in self._before(self.by_stock.get(sym, []), d)]
        sect = [abs(m) for m in self._before(self.by_sector.get(self.sector_of.get(sym, "Unknown"), []), d)]
        return typical_move(own, sect)

    def z(self, d: date, horizon: int = 1, centered: bool = True) -> np.ndarray:
        """The pooled standardized moves over `horizon` sessions, from reports before d. Centered: the pool's mean drift is removed, so a
        directional trade is priced on the size of report moves, never on the market's drift over the years in the pool."""
        pool = self.pools.get(max(1, min(int(horizon), MAX_HORIZON)), [])
        z = np.array([v for _, v in pool[: bisect_left(pool, (d, -1e9))]])
        return z - z.mean() if centered and len(z) else z


def horizon_sessions(chain_date: date, expiration: date) -> int:
    """Pure: the sessions from the chain date to the expiry inclusive (at least 1, at most MAX_HORIZON)."""
    from app.services.trading_calendar import is_trading_day, sessions_after
    n = sessions_after(chain_date, expiration) + (1 if is_trading_day(expiration) else 0)
    return max(1, min(n, MAX_HORIZON))


def typical_move(own_abs: list[float], sector_abs: list[float]) -> float | None:
    """Pure: the stock's typical absolute report move, shrunk toward its sector (fractions)."""
    if len(sector_abs) < MIN_SECTOR:
        return None
    ms = float(np.mean(sector_abs))
    if len(own_abs) < MIN_PRIOR:
        return ms
    n = len(own_abs)
    return (n * float(np.mean(own_abs)) + SHRINK_K * ms) / (n + SHRINK_K)


def p_beyond(z: np.ndarray, tau: float, move: float) -> float | None:
    """Pure: P(|report move| > move) from the standardized pool scaled by τ."""
    if len(z) < MIN_POOL or not tau:
        return None
    return float(np.mean(np.abs(z) * tau > move))


# ── quotes and structures ─────────────────────────────────────────────────────

def fill(q: dict | None, side: str, c: float) -> float | None:
    """Pure: the price a leg fills at (a buy at mid + c × spread, a sell at mid − c × spread, never below zero); None without a two-sided quote."""
    if not q or q.get("bid") is None or q.get("ask") is None or q["ask"] <= 0 or q["bid"] < 0 or q["ask"] < q["bid"]:
        return None
    m, s = (q["bid"] + q["ask"]) / 2, q["ask"] - q["bid"]
    return m + c * s if side == "buy" else max(0.0, m - c * s)


def intrinsic(kind: str, strike: float, spot: float) -> float:
    return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)


def quotes_by_strike(calls: list[dict], puts: list[dict]) -> dict[float, dict]:
    """{strike: {"call": quote, "put": quote}} for strikes quoted on both sides (courier-shaped rows: strike, bid, ask)."""
    out: dict[float, dict] = {}
    for kind, rows in (("call", calls), ("put", puts)):
        for r in rows or []:
            try:
                k = float(r["strike"])
            except (KeyError, TypeError, ValueError):
                continue
            out.setdefault(k, {})[kind] = {"bid": r.get("bid"), "ask": r.get("ask")}
    return {k: v for k, v in out.items() if "call" in v and "put" in v}


def nearest(strikes: list[float], target: float) -> float | None:
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


def implied_move(quotes: dict[float, dict], spot: float) -> tuple[float, float] | None:
    """(ATM strike, the straddle mid over spot) at the strike nearest spot, or None without a priced pair."""
    strikes = sorted(quotes)
    atm = nearest(strikes, spot)
    if atm is None:
        return None
    cm, pm = fill(quotes[atm]["call"], "buy", 0.0), fill(quotes[atm]["put"], "buy", 0.0)
    if cm is None or pm is None or cm + pm <= 0:
        return None
    return atm, (cm + pm) / spot


def structure_legs(name: str, quotes: dict[float, dict], spot: float, im: float, tau: float) -> list[dict] | None:
    """Pure: the legs of one structure as (kind, side, strike, quote), by the research's strike choices."""
    strikes = sorted(quotes)
    atm = nearest(strikes, spot)
    if atm is None:
        return None
    above = [k for k in strikes if k > atm]
    below = [k for k in strikes if k < atm]
    def leg(kind, side, k):
        return {"kind": kind, "side": side, "strike": k, "bid": quotes[k][kind]["bid"], "ask": quotes[k][kind]["ask"]}
    if name == "long_call":
        return [leg("call", "buy", atm)]
    if name == "long_straddle":
        return [leg("call", "buy", atm), leg("put", "buy", atm)]
    if name == "bull_call_spread":
        if not above:
            return None
        short = nearest(above, spot * (1 + tau))
        return [leg("call", "buy", atm), leg("call", "sell", short)]
    if name == "iron_condor":
        sc, sp = nearest(above, spot * (1 + im)), nearest(below, spot * (1 - im))
        if sc is None or sp is None:
            return None
        lc, lp = nearest([k for k in strikes if k > sc], spot * (1 + 2 * im)), nearest([k for k in strikes if k < sp], spot * (1 - 2 * im))
        if lc is None or lp is None:
            return None
        return [leg("call", "sell", sc), leg("put", "sell", sp), leg("call", "buy", lc), leg("put", "buy", lp)]
    raise ValueError(name)


def entry_cost(legs: list[dict], c: float) -> float | None:
    """Pure: the net debit per share (negative for a credit) at fills with c."""
    total = 0.0
    for L in legs:
        f = fill({"bid": L["bid"], "ask": L["ask"]}, L["side"], c)
        if f is None:
            return None
        total += f if L["side"] == "buy" else -f
    return total


def payoff(legs: list[dict], final_spot: float) -> float:
    """Pure: the structure's value per share at expiration."""
    return sum((1 if L["side"] == "buy" else -1) * intrinsic(L["kind"], L["strike"], final_spot) for L in legs)


def max_loss(name: str, legs: list[dict], cost: float) -> float | None:
    if name == "iron_condor":
        sc = next(L["strike"] for L in legs if L["kind"] == "call" and L["side"] == "sell")
        lc = next(L["strike"] for L in legs if L["kind"] == "call" and L["side"] == "buy")
        sp = next(L["strike"] for L in legs if L["kind"] == "put" and L["side"] == "sell")
        lp = next(L["strike"] for L in legs if L["kind"] == "put" and L["side"] == "buy")
        width = min(lc - sc, sp - lp)
        credit = -cost
        return width - credit if credit > 0 and width - credit > 0 else None
    return cost if cost > 0 else None


def breakeven_pct(name: str, legs: list[dict], cost: float, spot: float) -> float:
    """Pure: the move (as a fraction of spot) at which the structure neither gains nor loses."""
    if name == "long_call":
        return (legs[0]["strike"] + cost) / spot - 1
    if name == "long_straddle":
        return cost / spot
    if name == "bull_call_spread":
        return (legs[0]["strike"] + cost) / spot - 1
    sc = next(L["strike"] for L in legs if L["kind"] == "call" and L["side"] == "sell")
    sp = next(L["strike"] for L in legs if L["kind"] == "put" and L["side"] == "sell")
    return (-cost + (sc - sp) / 2) / spot


def evaluate_structure(name: str, legs: list[dict], spot: float, tau: float, z: np.ndarray) -> dict | None:
    """Pure: the card's figures for one structure, at the real bid and ask and at a full spread."""
    cost = entry_cost(legs, 0.5)
    cost_full = entry_cost(legs, 1.0)
    if cost is None or cost_full is None:
        return None
    risk, risk_full = max_loss(name, legs, cost), max_loss(name, legs, cost_full)
    if risk is None or risk_full is None or len(z) < MIN_POOL:
        return None
    finals = spot * (1 + z * tau)
    pays = np.array([payoff(legs, s) for s in finals])
    ev = float(np.mean(pays - cost) / risk * 100)
    ev_full = float(np.mean(pays - cost_full) / risk_full * 100)
    return {"legs": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in L.items()} for L in legs],
            "cost_per_contract": round(cost * 100, 2), "max_loss_per_contract": round(risk * 100, 2),
            "breakeven_pct": round(breakeven_pct(name, legs, cost, spot) * 100, 2), "p_profit": round(float(np.mean(pays - cost > 0)), 3),
            "ev_per_100": round(ev, 2), "ev_per_100_full_spread": round(ev_full, 2), "expected_payoff_method": EXPECTED_PAYOFF_METHOD}


def verdict_for(structures: dict[str, dict]) -> tuple[str, str | None]:
    """Pure: "possible_edge" only when a structure clears zero at a full spread (that structure named); else "no_edge"."""
    best = max(((s["ev_per_100_full_spread"], n) for n, s in structures.items() if s), default=None)
    if best and best[0] > 0:
        return VERDICT_POSSIBLE_EDGE, best[1]
    return VERDICT_NO_EDGE, None


def build_card(*, symbol: str, report_date: date, report_confirmation: str | None, chain: dict, chain_date: str | None, chain_source: str | None,
               expiration: str, spot: float, odds: Odds, today: date, computed_at: datetime | None = None) -> dict | str:
    """The card, or the reason none could be built (a string)."""
    quotes = quotes_by_strike(chain.get("calls") or [], chain.get("puts") or [])
    if not quotes:
        return "no strike quoted on both sides"
    im = implied_move(quotes, spot)
    if im is None:
        return "no priced at-the-money pair"
    atm, implied = im
    tau = odds.tau(symbol, today)
    if not tau:
        return "not enough sector history for a typical move"
    h = horizon_sessions(date.fromisoformat(str(chain_date)[:10]), date.fromisoformat(expiration)) if chain_date else 1
    z = odds.z(today, h)
    if len(z) < MIN_POOL:
        return f"not enough pooled report moves over {h} session(s) for a probability"
    structures: dict[str, dict | None] = {}
    for name in STRUCTURES:
        legs = structure_legs(name, quotes, spot, implied, tau)
        structures[name] = evaluate_structure(name, legs, spot, tau, z) if legs else None
    if all(s is None for s in structures.values()):
        return "no structure could be priced from the quoted strikes"
    verdict, which = verdict_for({n: s for n, s in structures.items() if s})
    own = odds.own_moves(symbol, today)
    return {"symbol": symbol, "computed_at": (computed_at or datetime.now(timezone.utc)).isoformat(), "computation_version": PRICING_COMPUTATION_VERSION,
            "report_date": report_date.isoformat(), "report_confirmation": report_confirmation, "chain_date": chain_date, "chain_source": chain_source,
            "expiration": expiration, "spot": spot, "atm_strike": atm, "implied_move_pct": round(implied * 100, 2), "typical_move_pct": round(tau * 100, 2),
            "horizon_sessions": h, "pooled_move_to_expiry_pct": round(float(np.mean(np.abs(z))) * tau * 100, 2),
            "prior_n": len(own), "prior_moves": [{"date": d.isoformat(), "pct_1d": round(m * 100, 2)} for d, m in own[-PRIOR_MOVES_SHOWN:]],
            "p_beyond_implied": round(p_beyond(z, tau, implied), 3), "structures": structures, "verdict": verdict, "verdict_structure": which}


def band_problems(card: dict) -> list[str]:
    """Pure: which of the validate bands a stored card breaks."""
    out = []
    for k in ("implied_move_pct", "typical_move_pct", "p_beyond_implied"):
        lo, hi = BANDS[k]
        v = card.get(k)
        if v is None or not (lo <= v <= hi):
            out.append(f"{k}={v} outside [{lo}, {hi}]")
    lo, hi = BANDS["ev_per_100"]
    for name, s in (card.get("structures") or {}).items():
        for key in ("ev_per_100", "ev_per_100_full_spread"):
            v = (s or {}).get(key)
            if s and (v is None or not (lo <= v <= hi)):
                out.append(f"{name}.{key}={v} outside [{lo}, {hi}]")
    return out


def card_key(symbol: str) -> str:
    return CARD_KEY.format(sym=symbol)


def dumps(card: dict) -> str:
    return json.dumps(card, default=str)
