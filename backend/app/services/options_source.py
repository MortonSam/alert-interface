"""Which options chain a ticker's pages read, and whether it may be read at all.

Two stored sources (services/chain_store): the courier's chain (chain:{SYM}:{EXP}, captured on Sam's Mac after the close) and
Intrinio's end-of-day chain (intrinio_chain:{SYM}:{EXP}, stored by the nightly). settings.options_primary_source picks the
primary ("courier" by default); a ticker whose primary chain is missing, stale or fails the parity check falls back to the other
source's chain if that one passes, else every options figure for the ticker is hidden with the reason.

Put-call band (American options): at the at-the-money strike nearest the close S, with quotes on both sides, the call ask less
the put bid must not sit below the floor S - PV(dividends) - K, and the call bid less the put ask must not sit above the ceiling
S - K e^(-rT), by more than PARITY_TOLERANCE_PCT of S. S is the official close of the chain's date (price_bars_shadow). The
tolerance comes from the Oct 5-6 and Oct 8, 2026 nights judged on quotes: Intrinio's worst gap is 0.064% (NVDA) and its 99th
percentile 0.013%, so 0.5% leaves eight times the headroom while still catching MTD's Oct 6 courier chain (22.6%), WTW's
(16.2%) and COIN's (1.035%). On quotes the band is permissive when quotes are wide: it catches broken chains, not loose ones.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

PARITY_TOLERANCE_PCT = 0.5
COURIER, INTRINIO = "courier", "intrinio"
IV_SOURCE = {COURIER: "courier", INTRINIO: "intrinio_mid"}       # iv_history.iv_source written from each source's chains


def order(primary: str) -> list[str]:
    """The sources a ticker's pages may read, in turn. With the courier primary (the default until the switch) there is no fallback:
    pages read the courier's chain as before, now behind the parity check. With Intrinio primary, the courier is the fallback."""
    return [INTRINIO, COURIER] if primary == INTRINIO else [COURIER]


def _quote(q: dict) -> tuple[float, float] | None:
    """(bid, ask) of a contract with a real offer: ask above zero and not below the bid; a zero bid is a quote (nobody bidding)."""
    bid, ask = q.get("bid"), q.get("ask")
    if ask is None or ask <= 0 or bid is None or bid < 0 or ask < bid:
        return None
    return float(bid), float(ask)


@dataclass(frozen=True)
class Parity:
    ok: bool
    gap_pct: float | None        # how far the quotes sit outside the band, % of the close (0 inside it)
    strike: float | None
    reason: str | None           # why it fails or cannot be checked (for validate and the logs, never for visitors)
    detail: dict | None = None   # the quotes and the band, for the report


def parity(chain: dict, spot: float | None, chain_date: date, expiration: date, rate: float | None, dividends: list[tuple[date, float]],
           tolerance_pct: float | None = None) -> Parity:
    """Pure: the American put-call band at the front expiry's at-the-money strike, from the quotes. Early exercise lets C - P sit
    anywhere from S - PV(dividends) - K (floor) up to S - K e^(-rT) (ceiling). The chain fails only when even the most favourable
    quotes miss the band by more than the tolerance (a % of the close): call ask - put bid below the floor, or call bid - put ask
    above the ceiling. `dividends` are (ex-date, cash) pairs; those after the chain date and on or before the expiry count."""
    tol = PARITY_TOLERANCE_PCT if tolerance_pct is None else tolerance_pct
    if not spot or spot <= 0:
        return Parity(False, None, None, "no official close for the chain's date")
    if rate is None:
        return Parity(False, None, None, "no stored risk-free rate for the chain's date")
    t = (expiration - chain_date).days / 365.0
    if t <= 0:
        return Parity(False, None, None, "the front expiry is not after the chain's date")
    calls = {float(c["strike"]): _quote(c) for c in chain.get("calls", []) if c.get("strike") is not None}
    puts = {float(p["strike"]): _quote(p) for p in chain.get("puts", []) if p.get("strike") is not None}
    both = [k for k in calls.keys() & puts.keys() if calls[k] is not None and puts[k] is not None]
    if not both:
        return Parity(False, None, None, "no strike with a quoted call and put (an ask above zero on both)")
    k = min(both, key=lambda s: abs(s - spot))
    (cb, ca), (pb, pa) = calls[k], puts[k]
    pv_div = sum(a * math.exp(-rate * (d - chain_date).days / 365.0) for d, a in dividends if chain_date < d <= expiration and a)
    floor = spot - pv_div - k
    ceiling = spot - k * math.exp(-rate * t)
    below = (floor - (ca - pb)) / spot * 100           # > 0: even call ask - put bid sits under the floor
    above = ((cb - pa) - ceiling) / spot * 100         # > 0: even call bid - put ask sits over the ceiling
    gap = max(below, above, 0.0)
    detail = {"strike": k, "call_bid": cb, "call_ask": ca, "put_bid": pb, "put_ask": pa, "floor": round(floor, 4), "ceiling": round(ceiling, 4),
              "ca_minus_pb": round(ca - pb, 4), "cb_minus_pa": round(cb - pa, 4)}
    if gap > tol:
        side = "below the floor" if below >= above else "above the ceiling"
        return Parity(False, round(gap, 3), k, f"the at-the-money quotes at {k:g} sit {gap:.2f}% of the close {side} of the American "
                                              f"put-call band (limit {tol:g}%)", detail)
    return Parity(True, round(gap, 3), k, None, detail)


@dataclass(frozen=True)
class Serving:
    source: str | None           # the chain source the ticker's pages read, or None (hidden)
    chain_date: str | None
    reason: str | None           # why hidden, or why the fallback is in use: for validate and the logs, never for visitors
    provisional: bool = False    # checked against the courier's post-close price, not yet the official close
    hidden_by_check: bool = False  # hidden because a fresh chain failed the check (not merely missing or stale)


def choose(primary: str, verdicts: dict[str, dict | None]) -> Serving:
    """Pure: the serving source from each source's verdict {chain_date, fresh, ok, reason, provisional} (None: no chain)."""
    why = []
    failed_check = False
    for i, src in enumerate(order(primary)):
        v = verdicts.get(src)
        label = "Intrinio" if src == INTRINIO else "courier"
        if not v:
            why.append(f"no {label} chain"); continue
        if not v.get("fresh"):
            why.append(f"the {label} chain of {v.get('chain_date')} is stale"); continue
        if not v.get("ok"):
            failed_check = True
            why.append(f"the {label} chain of {v.get('chain_date')} fails the put-call band check: {v.get('reason')}"); continue
        return Serving(src, v.get("chain_date"), ("fallback: " + "; ".join(why)) if i else None, bool(v.get("provisional")))
    return Serving(None, None, "options hidden: " + "; ".join(why), hidden_by_check=failed_check)


# ── stored verdicts and the read-time resolver ──────────────────────────────────────────────────────────────────────────────────

VERDICT_KEY = "chain_parity:{sym}"         # {"courier": verdict, "intrinio": verdict}, written nightly by scripts/check_chain_parity.py
_CACHE: dict[tuple, dict] = {}             # (sym, source, chain_date, spot_source) -> verdict, for chains newer than the stored verdict
_CACHE_MAX = 4000


async def _chain_and_front(db, sym: str, source: str):
    """(newest chain date, its front expiry, that chain) for a source: the newest chain_last_trade across the source's stored
    expirations (one a night's run skipped keeps its older date and is not the newest batch), and the earliest expiration after that
    date stored in that batch."""
    import sqlalchemy as sa
    from app.services import chain_store
    prefix = chain_store._PREFIX[source]
    rows = (await db.execute(sa.text("SELECT key, value::json->>'chain_last_trade' FROM system_metadata WHERE key LIKE :p"),
                             {"p": f"{prefix}:{sym}:%"})).all()
    dated = [(k.split(":")[2], (d or "")[:10]) for k, d in rows if len(k.split(":")) == 3 and d]
    if not dated:
        return None, None, None
    chain_date = max(d for _, d in dated)
    later = sorted(e for e, d in dated if d == chain_date and e > chain_date)
    if not later:
        return chain_date, None, None
    got = await chain_store.get_chain(db, sym, later[0], source=source)
    return chain_date, later[0], (got[0] if got else None)


async def compute_verdict(db, sym: str, source: str) -> dict | None:
    """The verdict for a source's newest chain, or None when the source has no chain for the ticker. Uses the stored verdict when it
    covers this chain date against the official close; otherwise computes one (and caches it in the process)."""
    import json as _json
    import sqlalchemy as sa
    from app.services import chain_store
    from app.services.chain_shadow import captured_after_close
    from app.services.rates import rate_on
    chain_date, exp, front = await _chain_and_front(db, sym, source)
    if not chain_date:
        return None
    fresh = chain_store.is_fresh(chain_date)
    raw = (await db.execute(sa.text("SELECT value FROM system_metadata WHERE key = :k"), {"k": VERDICT_KEY.format(sym=sym)})).scalar()
    stored = (_json.loads(raw) if raw else {}).get(source) if raw else None
    if stored and stored.get("chain_date") == chain_date and stored.get("spot_source") == "official close":
        return {**stored, "fresh": fresh}
    if front is None:
        return {"chain_date": chain_date, "fresh": fresh, "ok": False, "reason": "no front expiry after the chain's date", "spot_source": None}
    close = (await db.execute(sa.text("SELECT close FROM price_bars_shadow WHERE symbol = :s AND date = :d"), {"s": sym, "d": date.fromisoformat(chain_date)})).scalar()
    spot, spot_source, provisional = (float(close), "official close", False) if close is not None else (None, None, False)
    if spot is None and source == COURIER and captured_after_close(front.get("chain_captured_at")) and front.get("underlying_price"):
        spot, spot_source, provisional = float(front["underlying_price"]), "courier post-close price", True
    key = (sym, source, chain_date, spot_source)
    if key in _CACHE:
        return {**_CACHE[key], "fresh": fresh}
    rate = (await rate_on(db, date.fromisoformat(chain_date))).rate
    divs = [(r[0], float(r[1])) for r in (await db.execute(sa.text("""
        SELECT e.event_date, (e.metadata->>'dividend_amount')::float FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE t.symbol = :s AND e.event_type = 'ex_dividend' AND e.event_date > :d AND e.event_date <= :x AND e.metadata ? 'dividend_amount'"""),
        {"s": sym, "d": date.fromisoformat(chain_date), "x": date.fromisoformat(exp)})).all() if r[1] is not None]
    pv = parity(front, spot, date.fromisoformat(chain_date), date.fromisoformat(exp), rate, divs)
    verdict = {"chain_date": chain_date, "expiration": exp, "ok": pv.ok, "gap_pct": pv.gap_pct, "strike": pv.strike, "reason": pv.reason,
               "spot": spot, "spot_source": spot_source, "provisional": provisional}
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = verdict
    return {**verdict, "fresh": fresh}


RESOLVE_TTL_SECONDS = 60          # chains change only when the courier lands or the nightly runs; a page reads a ticker's chain many times
_RESOLVED: dict[tuple[str, str], tuple[float, Serving]] = {}


async def resolve(db, sym: str, primary: str | None = None) -> Serving:
    """The chain source a ticker's pages read now (settings.options_primary_source unless `primary` is given)."""
    import time as _time
    from app.config import settings
    primary = primary or settings.options_primary_source
    hit = _RESOLVED.get((sym, primary))
    if hit and _time.monotonic() - hit[0] < RESOLVE_TTL_SECONDS:
        return hit[1]
    verdicts: dict[str, dict | None] = {}
    for src in order(primary):                      # lazily: a source that serves ends the search (the fallback is not read)
        verdicts[src] = await compute_verdict(db, sym, src)
        v = verdicts[src]
        if v and v.get("fresh") and v.get("ok"):
            break
    serving = choose(primary, verdicts)
    if serving.hidden_by_check or (serving.reason and serving.reason.startswith("fallback:")):
        import logging
        logging.getLogger("options_source").info("%s: %s", sym, serving.reason)       # the full reason, for the logs only
    if len(_RESOLVED) > _CACHE_MAX:
        _RESOLVED.clear()
    _RESOLVED[(sym, primary)] = (_time.monotonic(), serving)
    return serving


def forget(sym: str) -> None:
    """A chain for `sym` was just stored: its next read resolves afresh."""
    for key in [k for k in _RESOLVED if k[0] == sym]:
        _RESOLVED.pop(key, None)


def clear_caches() -> None:
    _CACHE.clear()
    _RESOLVED.clear()


NO_OPTIONS_NOTE = "No current options data is available for this ticker"
# Sam's wording, exactly, for every page a failed check hides. No vendor name, no "courier" or "parity", no percentage: the full
# reason stays in validate (chain_parity) and the logs.
PAUSED_NOTE = ("Options figures for this stock are paused until the next update. The latest options quotes didn't line up with the "
               "stock's closing price, so we're holding them back.")


async def no_options_note(db, sym: str) -> str:
    """The visitor-facing note when a page has no chain to read: PAUSED_NOTE when a check hid it, else the general one."""
    sv = await resolve(db, sym)
    if sv.source is None and sv.hidden_by_check:
        return PAUSED_NOTE
    return NO_OPTIONS_NOTE
