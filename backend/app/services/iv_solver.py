"""In-house implied volatility: Black-Scholes, European, no dividends, solved by Brent's method from a contract mid.

Every assumption is a named constant below. Any change to one bumps IV_SOLVER_VERSION so stored rows stay comparable.
The inputs a row stores (mid, spot, rate, days) are enough to re-derive it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from scipy.optimize import brentq
from scipy.stats import norm

IV_SOLVER_VERSION = 1

DAY_COUNT = 365              # time to expiry is calendar days from the chain date to the expiry, over 365
DIVIDEND_YIELD = 0.0         # no dividend term: the front expiry rarely spans an ex-date, and the error is below the vendor band
RATE_SERIES = "DTB3"         # FRED 3-month Treasury bill, secondary market, discount basis, percent
RATE_SCALE = 0.01            # percent to decimal; the discount-basis rate is used as the continuous rate, a few bp of difference
RATE_MAX_AGE_SESSIONS = 5    # a rate older than this many sessions before the chain date is no rate: the step fails closed
IV_BRACKET_LOW = 0.001       # Brent's bracket: a volatility below 0.1% is no market
IV_BRACKET_HIGH = 10.0       # and above 1000% is no market either
BRENT_XTOL = 1e-8            # absolute tolerance on sigma
BRENT_MAXITER = 200
MIN_EXPIRY_DAYS = 7          # the expiry rule snapshot_iv uses: the nearest expiry at least this many days out, else the farthest
IV_SANITY_MIN = 0.02         # validate's solver band: a solved IV outside [IV_SANITY_MIN, IV_SANITY_MAX] is an ERROR
IV_SANITY_MAX = 5.0


@dataclass(frozen=True)
class Solve:
    iv: float | None
    reason: str | None       # why iv is None


def mid(bid, ask) -> float | None:
    """The contract price the solver takes: the bid/ask midpoint, both quoted above zero. No last-trade fallback."""
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (float(bid) + float(ask)) / 2.0


def time_to_expiry(chain_date: date, expiration: date) -> tuple[int, float]:
    """(calendar days, years) from the chain date to the expiry."""
    days = (expiration - chain_date).days
    return days, days / DAY_COUNT


def choose_expiration(expirations: list[str], on: date) -> str | None:
    """snapshot_iv's rule: the nearest expiry on or after `on` + MIN_EXPIRY_DAYS, else the farthest available."""
    exps = sorted(e for e in expirations if e)
    if not exps:
        return None
    floor = (on + timedelta(days=MIN_EXPIRY_DAYS)).isoformat()
    later = [e for e in exps if e >= floor]
    return later[0] if later else exps[-1]


def bs_price(kind: str, spot: float, strike: float, t: float, rate: float, sigma: float, q: float = DIVIDEND_YIELD) -> float:
    """Black-Scholes European price. kind is "call" or "put"."""
    if t <= 0 or sigma <= 0:
        fwd = spot * math.exp(-q * t) - strike * math.exp(-rate * t)
        return max(fwd, 0.0) if kind == "call" else max(-fwd, 0.0)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if kind == "call":
        return spot * math.exp(-q * t) * norm.cdf(d1) - strike * math.exp(-rate * t) * norm.cdf(d2)
    return strike * math.exp(-rate * t) * norm.cdf(-d2) - spot * math.exp(-q * t) * norm.cdf(-d1)


def implied_vol(kind: str, price: float | None, spot: float | None, strike: float | None, t: float, rate: float) -> Solve:
    """The sigma at which bs_price equals `price`, by Brent's method on [IV_BRACKET_LOW, IV_BRACKET_HIGH]."""
    if price is None:
        return Solve(None, "no mid: bid or ask missing or zero")
    if not spot or spot <= 0 or not strike or strike <= 0:
        return Solve(None, "no spot or strike")
    if t <= 0:
        return Solve(None, "expiry is not after the chain date")
    lo, hi = bs_price(kind, spot, strike, t, rate, IV_BRACKET_LOW), bs_price(kind, spot, strike, t, rate, IV_BRACKET_HIGH)
    if price <= lo:
        return Solve(None, f"mid {price:.4f} at or below the no-volatility price {lo:.4f}")
    if price >= hi:
        return Solve(None, f"mid {price:.4f} at or above the price at {IV_BRACKET_HIGH:.0%} volatility ({hi:.4f})")
    sigma = brentq(lambda s: bs_price(kind, spot, strike, t, rate, s) - price, IV_BRACKET_LOW, IV_BRACKET_HIGH, xtol=BRENT_XTOL, maxiter=BRENT_MAXITER)
    return Solve(float(sigma), None)


def atm_strike(calls: list[dict], puts: list[dict], spot: float) -> float | None:
    """The strike nearest the spot among strikes quoted on both sides."""
    both = {float(c["strike"]) for c in calls if c.get("strike") is not None} & {float(p["strike"]) for p in puts if p.get("strike") is not None}
    return min(both, key=lambda k: abs(k - spot)) if both and spot else None


@dataclass(frozen=True)
class AtmSolve:
    strike: float | None
    call_mid: float | None
    put_mid: float | None
    call: Solve
    put: Solve
    vendor_call_iv: float | None
    vendor_put_iv: float | None
    days: int | None
    t: float | None

    @property
    def atm_iv(self) -> float | None:
        ivs = [s.iv for s in (self.call, self.put) if s.iv is not None]
        return sum(ivs) / len(ivs) if ivs else None

    @property
    def vendor_iv(self) -> float | None:
        ivs = [v for v in (self.vendor_call_iv, self.vendor_put_iv) if v is not None]
        return sum(ivs) / len(ivs) if ivs else None

    @property
    def reason(self) -> str | None:
        if self.strike is None:
            return "no strike quoted on both sides"
        parts = [f"{side}: {s.reason}" for side, s in (("call", self.call), ("put", self.put)) if s.iv is None]
        return "; ".join(parts) or None


def solve_atm(chain: dict, spot: float, chain_date: date, expiration: date, rate: float) -> AtmSolve:
    """Solve the ATM call and put of one chain (courier-shaped: strike, bid, ask, impliedVolatility) at `spot`."""
    calls, puts = chain.get("calls", []), chain.get("puts", [])
    k = atm_strike(calls, puts, spot)
    days, t = time_to_expiry(chain_date, expiration)
    if k is None:
        return AtmSolve(None, None, None, Solve(None, "no strike"), Solve(None, "no strike"), None, None, days, t)
    c = next(x for x in calls if float(x["strike"]) == k)
    p = next(x for x in puts if float(x["strike"]) == k)
    cm, pm = mid(c.get("bid"), c.get("ask")), mid(p.get("bid"), p.get("ask"))
    return AtmSolve(k, cm, pm, implied_vol("call", cm, spot, k, t, rate), implied_vol("put", pm, spot, k, t, rate),
                    c.get("impliedVolatility"), p.get("impliedVolatility"), days, t)
