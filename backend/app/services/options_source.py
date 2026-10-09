"""Which options chain a ticker's pages read, and whether it may be read at all.

Two stored sources (services/chain_store): the courier's chain (chain:{SYM}:{EXP}, captured on Sam's Mac after the close) and
Intrinio's end-of-day chain (intrinio_chain:{SYM}:{EXP}, stored by the nightly). settings.options_primary_source picks the
primary ("courier" by default); a ticker whose primary chain is missing, stale or fails the parity check falls back to the other
source's chain if that one passes, else every options figure for the ticker is hidden with the reason.

Put-call parity: the front expiry's at-the-money call and put must satisfy C - P = S - PV(dividends) - K e^(-rT) within
PARITY_TOLERANCE_PCT of S, with S the official close of the chain's date (price_bars_shadow). A courier chain captured after
the 16:00 close is checked against its own post-close price until the nightly stores the official close, and the check is
then marked provisional. The tolerance comes from the Oct 5-6, 2026 shadow nights (931 ticker-nights per source): the 32
disagreements where both chains were internally consistent (quote timing) reach at most 0.87% (FOX, Oct 5); Intrinio's 99th
percentile is 0.95%; the two chains that had to be caught sit beyond it: MTD's courier put at 22.7% and CHTR's Oct 6 Intrinio
chain at 1.10%. At 1.0% the two nights hide 20 of 931 courier chains and 9 of 931 Intrinio chains.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

PARITY_TOLERANCE_PCT = 1.0
COURIER, INTRINIO = "courier", "intrinio"
IV_SOURCE = {COURIER: "courier", INTRINIO: "intrinio_mid"}       # iv_history.iv_source written from each source's chains


def order(primary: str) -> list[str]:
    """The sources a ticker's pages may read, in turn. With the courier primary (the default until the switch) there is no fallback:
    pages read the courier's chain as before, now behind the parity check. With Intrinio primary, the courier is the fallback."""
    return [INTRINIO, COURIER] if primary == INTRINIO else [COURIER]


def _mid(q: dict) -> float | None:
    bid, ask = q.get("bid"), q.get("ask")
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (float(bid) + float(ask)) / 2


@dataclass(frozen=True)
class Parity:
    ok: bool
    gap_pct: float | None        # (C - P - forward) / S * 100
    strike: float | None
    reason: str | None           # why it fails or cannot be checked


def parity(chain: dict, spot: float | None, chain_date: date, expiration: date, rate: float | None, dividends: list[tuple[date, float]]) -> Parity:
    """Pure: the front expiry's at-the-money parity check. `dividends` are (ex-date, cash) pairs; those after the chain date and on or
    before the expiry reduce the forward by their present value."""
    if not spot or spot <= 0:
        return Parity(False, None, None, "no official close for the chain's date")
    if rate is None:
        return Parity(False, None, None, "no stored risk-free rate for the chain's date")
    t = (expiration - chain_date).days / 365.0
    if t <= 0:
        return Parity(False, None, None, "the front expiry is not after the chain's date")
    calls = {float(c["strike"]): _mid(c) for c in chain.get("calls", []) if c.get("strike") is not None}
    puts = {float(p["strike"]): _mid(p) for p in chain.get("puts", []) if p.get("strike") is not None}
    both = [k for k in calls.keys() & puts.keys() if calls[k] is not None and puts[k] is not None]
    if not both:
        return Parity(False, None, None, "no strike with a quoted call and put (bid and ask above zero)")
    k = min(both, key=lambda s: abs(s - spot))
    pv_div = sum(a * math.exp(-rate * (d - chain_date).days / 365.0) for d, a in dividends if chain_date < d <= expiration and a)
    gap = ((calls[k] - puts[k]) - (spot - pv_div - k * math.exp(-rate * t))) / spot * 100
    if abs(gap) > PARITY_TOLERANCE_PCT:
        return Parity(False, round(gap, 3), k, f"the at-the-money call and put at {k:g} break put-call parity by {gap:+.2f}% of the close "
                                              f"(limit {PARITY_TOLERANCE_PCT:g}%)")
    return Parity(True, round(gap, 3), k, None)


@dataclass(frozen=True)
class Serving:
    source: str | None           # the chain source the ticker's pages read, or None (hidden)
    chain_date: str | None
    reason: str | None           # why hidden, or why the fallback is in use
    provisional: bool = False    # parity checked against the courier's post-close price, not yet the official close


def choose(primary: str, verdicts: dict[str, dict | None]) -> Serving:
    """Pure: the serving source from each source's verdict {chain_date, fresh, ok, reason, provisional} (None: no chain)."""
    why = []
    for i, src in enumerate(order(primary)):
        v = verdicts.get(src)
        label = "Intrinio" if src == INTRINIO else "courier"
        if not v:
            why.append(f"no {label} chain"); continue
        if not v.get("fresh"):
            why.append(f"the {label} chain of {v.get('chain_date')} is stale"); continue
        if not v.get("ok"):
            why.append(f"the {label} chain of {v.get('chain_date')} fails the parity check: {v.get('reason')}"); continue
        return Serving(src, v.get("chain_date"), ("fallback: " + "; ".join(why)) if i else None, bool(v.get("provisional")))
    return Serving(None, None, "options hidden: " + "; ".join(why))


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
    serving = choose(primary, {src: await compute_verdict(db, sym, src) for src in order(primary)})
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


async def no_options_note(db, sym: str) -> str:
    """The visitor-facing note when a page has no chain to read: the reason when the options are hidden by a check, else the general one."""
    sv = await resolve(db, sym)
    if sv.source is None and sv.reason and "parity" in sv.reason:
        return "Options figures are hidden for this ticker: " + sv.reason.removeprefix("options hidden: ")
    return NO_OPTIONS_NOTE
