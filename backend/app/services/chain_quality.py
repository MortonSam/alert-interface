"""One filter for every stored options chain: chain_store.put_chain applies it to both sources before a chain is written, so
every reader (the expected move, the ticker page's options panels, Ivy's vol gate, the parity check, Build a Trade) gets the
standard contracts only. Build a Trade keeps its own checks as a second line.

Intrinio lists a split or spun-off stock's adjusted contracts beside the standard ones at the same strikes, under the root with a
digit added (PANW1 beside PANW: the $420 December call at $550 beside $40; BDX1, HON2, DD2). Three rules, in order:
  1. a contract whose root is the stock's root plus digits is adjusted, and dropped (Intrinio chains keep the root);
  2. a quote no standard 100-share contract could carry is dropped: implied volatility above MAX_SANE_IV, a call priced at or
     above the stock (a call is never worth more than the shares), or a put priced at or above its strike (never worth more
     than the cash it delivers);
  3. a strike still listed twice on one side keeps the contract with the most open interest.
validate_data.check_chain_quality reports any stored chain that breaks them.
"""
from __future__ import annotations

import re

MAX_SANE_IV = 5.0    # 500% implied volatility: above this a quote is not a standard contract's
SIDES = ("calls", "puts")


def quote_mid(c: dict) -> float | None:
    """The bid/ask midpoint, else the last trade (ivy_v2._mid_or_last's rule)."""
    bid, ask, last = c.get("bid"), c.get("ask"), c.get("lastPrice")
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


def _norm(root: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (root or "").upper())


def adjusted_root(root: str | None, stock_root: str | None) -> bool:
    """Whether a contract's root is the stock's root with digits added (an adjusted deliverable)."""
    r, s = _norm(root), _norm(stock_root)
    return bool(r and s and r != s and re.fullmatch(re.escape(s) + r"\d+", r))


def nonstandard_reason(c: dict, side: str, spot: float | None, stock_root: str | None = None) -> str | None:
    """Why a contract cannot be a standard one ('root', 'iv', 'price'), or None."""
    if adjusted_root(c.get("root"), stock_root):
        return "root"
    iv = c.get("impliedVolatility")
    if iv is not None and iv > MAX_SANE_IV:
        return "iv"
    mid = quote_mid(c)
    if mid is not None:
        if side == "calls" and spot and spot > 0 and mid >= spot:
            return "price"
        if side == "puts" and c.get("strike") and mid >= c["strike"]:
            return "price"
    return None


def _rank(c: dict) -> tuple[float, float]:
    return (c.get("openInterest") or 0, c.get("volume") or 0)


def stock_root(chain: dict, symbol: str | None = None) -> str | None:
    return chain.get("intrinio_ticker") or symbol


def clean_side(contracts: list[dict], side: str, spot: float | None, root: str | None = None) -> tuple[list[dict], int, int]:
    """(kept contracts in strike order, dropped as non-standard, dropped as a duplicate strike)."""
    standard = [c for c in contracts if nonstandard_reason(c, side, spot, root) is None]
    by_strike: dict = {}
    for c in standard:
        k = c.get("strike")
        if k not in by_strike or _rank(c) > _rank(by_strike[k]):
            by_strike[k] = c
    kept = sorted(by_strike.values(), key=lambda c: c.get("strike") or 0)
    return kept, len(contracts) - len(standard), len(standard) - len(kept)


def clean_chain(chain: dict, symbol: str | None = None) -> dict:
    """A copy of the chain with both sides cleaned and the counts dropped recorded under chain_quality."""
    spot, root = chain.get("underlying_price"), stock_root(chain, symbol)
    out = dict(chain)
    nonstandard = duplicates = 0
    for side in SIDES:
        kept, ns, dup = clean_side(chain.get(side) or [], side, spot, root)
        out[side] = kept
        nonstandard += ns
        duplicates += dup
    prior = chain.get("chain_quality") or {}
    out["chain_quality"] = {"dropped_nonstandard": nonstandard + (prior.get("dropped_nonstandard") or 0),
                            "dropped_duplicates": duplicates + (prior.get("dropped_duplicates") or 0)}
    return out


def problems(chain: dict, symbol: str | None = None) -> dict:
    """Counts of stored contracts breaking the rules: {'root', 'iv', 'price', 'duplicate'}. All zero for a clean chain."""
    spot, root = chain.get("underlying_price"), stock_root(chain, symbol)
    out = {"root": 0, "iv": 0, "price": 0, "duplicate": 0}
    for side in SIDES:
        seen: set = set()
        for c in chain.get(side) or []:
            r = nonstandard_reason(c, side, spot, root)
            if r:
                out[r] += 1
            if c.get("strike") in seen:
                out["duplicate"] += 1
            seen.add(c.get("strike"))
    return out
