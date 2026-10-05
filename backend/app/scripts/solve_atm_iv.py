"""Nightly: the in-house ATM implied volatility from Intrinio's stored chains, written beside the courier rows, served nowhere.

Round trips are few: one query indexes every Intrinio chain key with its date (extracted server-side), then chains are
loaded, solved and written BATCH at a time, with the rate looked up once per chain date and progress recorded per batch.
For every ticker with an Intrinio chain (intrinio_chain:{SYM}:{EXP}, scripts/shadow_option_chains.py): the expiry
snapshot_iv's rule picks (services/iv_solver.choose_expiration) on the chain's own date, the stored close of that
date as spot (the chain's underlying_price, from price_bars_shadow), the FRED DTB3 rate for that date (fetched and
stored first; the step fails closed when no rate within RATE_MAX_AGE_SESSIONS sessions exists), and Brent's method
on the ATM call and put mids. One iv_history row per ticker and chain date with iv_source "intrinio_mid",
iv_version IV_SOLVER_VERSION, the inputs, both solved sides and the vendor's IVs beside them. A ticker whose ATM call
or put mid is below MIN_ATM_MID (a nonstandard chain) gets no row and is named in the outcome under skipped_nonstandard.

Usage
-----
    python -m app.scripts.solve_atm_iv                           # the nightly step
    python -m app.scripts.solve_atm_iv --symbols=MU,CAT --on=2026-10-01
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.iv_history import SOLVER_SOURCE
from app.services import chain_store
from app.services.iv_solver import IV_SOLVER_VERSION, MIN_ATM_MID, choose_expiration, nonstandard_mids, solve_atm
from app.services.rates import fetch_series, rate_on, store_rates
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "ATM IV (solver)"
RATE_FETCH_SINCE_DAYS = 30


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def chain_index(only: set[str] | None) -> dict[str, dict[str, str]]:
    """{symbol: {expiration: chain_date}} from the stored Intrinio chain keys, with the date extracted server-side:
    one query, no chain bodies transferred."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT key, value::json->>'chain_last_trade' FROM system_metadata WHERE key LIKE 'intrinio_chain:%'"))).all()
    out: dict[str, dict[str, str]] = {}
    for key, d in rows:
        parts = key.split(":")
        if len(parts) == 3 and d and (not only or parts[1] in only):
            out.setdefault(parts[1], {})[parts[2]] = str(d)[:10]
    return out


def choose_targets(index: dict[str, dict[str, str]], on: str | None) -> list[tuple[str, str, date]]:
    """(symbol, expiration, chain_date) per symbol: the expiry the shared rule picks on the chain's own date.
    `on` keeps only chains dated that session."""
    out = []
    for sym in sorted(index):
        exps = {e: d for e, d in index[sym].items() if not on or d == on}
        if not exps:
            continue
        chain_date = date.fromisoformat(max(exps.values()))
        exp = choose_expiration([e for e, d in exps.items() if d == chain_date.isoformat()], chain_date)
        if exp:
            out.append((sym, exp, chain_date))
    return out


async def load_chains(keys: list[str]) -> dict[str, dict]:
    """The chain bodies for these keys, one query."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT key, value FROM system_metadata WHERE key = ANY(:k)"), {"k": keys})).all()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except (ValueError, TypeError):
            continue
    return out


def solve_target(sym: str, chain: dict, exp: str, chain_date: date, rate, rate_date) -> tuple[str, dict]:
    """One ticker's outcome: ("row", upsert params) | ("nonstandard", what the outcome records) | ("skip", {"reason"})."""
    spot = chain.get("underlying_price")
    if not spot:
        return "skip", {"reason": "no stored close for the chain date"}
    a = solve_atm(chain, float(spot), chain_date, date.fromisoformat(exp), rate)
    if nonstandard_mids(a.call_mid, a.put_mid):
        # no row: a solved number from a penny quote would be a wrong IV, and iv_solver_band is for real solves
        return "nonstandard", {"spot": float(spot), "strike": a.strike, "call_mid": round(a.call_mid, 4) if a.call_mid is not None else None,
                               "put_mid": round(a.put_mid, 4) if a.put_mid is not None else None, "expiration": exp, "floor": MIN_ATM_MID}
    return "row", {"symbol": sym, "date": chain_date, "iv_source": SOLVER_SOURCE, "iv_version": IV_SOLVER_VERSION, "expiration": date.fromisoformat(exp),
                   "atm_strike": a.strike, "current_price": float(spot), "atm_iv": a.atm_iv, "atm_iv_reason": a.reason,
                   "atm_call_mid": a.call_mid, "atm_put_mid": a.put_mid, "solved_call_iv": a.call.iv, "solved_put_iv": a.put.iv,
                   "vendor_call_iv": a.vendor_call_iv, "vendor_put_iv": a.vendor_put_iv, "vendor_iv": a.vendor_iv,
                   "rate": rate, "rate_date": rate_date, "days_to_expiry": a.days,
                   "_sides": sum(1 for x in (a.call, a.put) if x.iv is not None)}


BATCH = 25      # chains loaded, solved and written per round trip; bounds memory to a few MB of chain JSON at a time


UPSERT = text("""
    INSERT INTO iv_history (id, symbol, date, iv_source, iv_version, expiration, atm_strike, current_price, atm_iv, atm_iv_reason,
                            atm_call_mid, atm_put_mid, solved_call_iv, solved_put_iv, vendor_call_iv, vendor_put_iv, vendor_iv,
                            rate, rate_date, days_to_expiry, created_at)
    VALUES (gen_random_uuid(), :symbol, :date, :iv_source, :iv_version, :expiration, :atm_strike, :current_price, :atm_iv, :atm_iv_reason,
            :atm_call_mid, :atm_put_mid, :solved_call_iv, :solved_put_iv, :vendor_call_iv, :vendor_put_iv, :vendor_iv,
            :rate, :rate_date, :days_to_expiry, now())
    ON CONFLICT (symbol, date, iv_source) DO UPDATE SET
        iv_version = EXCLUDED.iv_version, expiration = EXCLUDED.expiration, atm_strike = EXCLUDED.atm_strike, current_price = EXCLUDED.current_price,
        atm_iv = EXCLUDED.atm_iv, atm_iv_reason = EXCLUDED.atm_iv_reason, atm_call_mid = EXCLUDED.atm_call_mid, atm_put_mid = EXCLUDED.atm_put_mid,
        solved_call_iv = EXCLUDED.solved_call_iv, solved_put_iv = EXCLUDED.solved_put_iv, vendor_call_iv = EXCLUDED.vendor_call_iv,
        vendor_put_iv = EXCLUDED.vendor_put_iv, vendor_iv = EXCLUDED.vendor_iv, rate = EXCLUDED.rate, rate_date = EXCLUDED.rate_date,
        days_to_expiry = EXCLUDED.days_to_expiry, created_at = now()
""")


async def run(argv: list[str]) -> int:
    only = {x.strip().upper() for x in _arg(argv, "symbols").split(",")} if _arg(argv, "symbols") else None
    on_arg = _arg(argv, "on")
    # 1. the rate, fetched and stored with its date; fail closed without one
    rate_fetch_error = None
    try:
        rows = await fetch_series(since=date.today() - timedelta(days=RATE_FETCH_SINCE_DAYS))
        async with ScriptSessionLocal() as s:
            stored = await store_rates(s, rows)
            await s.commit()
    except Exception as exc:
        rate_fetch_error, stored = str(exc)[:160], 0
    # 2. which chain per ticker, from keys and dates only
    targets = choose_targets(await chain_index(only), on_arg)
    skipped_stale: dict[str, str] = {}
    if not on_arg:                                   # an explicit --on is a historic run; the nightly refuses a stale chain
        fresh_targets = []
        for sym, exp, d in targets:
            if chain_store.is_fresh(d.isoformat()):
                fresh_targets.append((sym, exp, d))
            else:
                skipped_stale[sym] = f"options chain is {chain_store.trading_days_since(d.isoformat())} sessions old"
        targets = fresh_targets
    rates: dict[date, object] = {}
    written = 0
    solved_both = solved_one = 0
    skipped: dict[str, str] = {}
    skipped_nonstandard: dict[str, dict] = {}
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i + BATCH]
        for _, _, d in batch:
            if d not in rates:
                async with ScriptSessionLocal() as s:
                    rates[d] = await rate_on(s, d)
                if rates[d].rate is None:
                    r = rates[d]
                    await record_step_fields(STEP_LABEL, {"error": f"no rate: {r.reason}" + (f"; fetch failed: {rate_fetch_error}" if rate_fetch_error else ""),
                                                          "rates_stored": stored, "written": written, "progress": {"done": i, "of": len(targets)}})
                    print(f"{STEP_LABEL}: failed closed, {r.reason}" + (f" (fetch: {rate_fetch_error})" if rate_fetch_error else ""))
                    return 1
        chains = await load_chains([chain_store.chain_key(sym, exp, chain_store.INTRINIO) for sym, exp, _ in batch])
        rows_out: list[dict] = []
        stale: list[tuple[str, date]] = []
        for sym, exp, d in batch:
            chain = chains.get(chain_store.chain_key(sym, exp, chain_store.INTRINIO))
            if chain is None:
                skipped[sym] = "chain missing"
                continue
            kind, info = solve_target(sym, chain, exp, d, rates[d].rate, rates[d].rate_date)
            if kind == "skip":
                skipped[sym] = info["reason"]
            elif kind == "nonstandard":
                skipped_nonstandard[sym] = info
                stale.append((sym, d))          # a row an earlier run wrote for this ticker and date is removed
            else:
                sides = info.pop("_sides")
                rows_out.append(info)
                solved_both += sides == 2
                solved_one += sides == 1
                if sides == 0:
                    skipped[sym] = info["atm_iv_reason"] or "unsolved"
        async with ScriptSessionLocal() as s:
            if rows_out:
                await s.execute(UPSERT, rows_out)
            for sym, d in stale:
                await s.execute(text("DELETE FROM iv_history WHERE symbol = :s AND date = :d AND iv_source = :src"), {"s": sym, "d": d, "src": SOLVER_SOURCE})
            await s.commit()
        written += len(rows_out)
        await record_step_fields(STEP_LABEL, {"progress": {"done": min(i + BATCH, len(targets)), "of": len(targets)}})
    rates_used = {d.isoformat(): f"{r.rate:.4%} ({r.rate_date.isoformat()})" for d, r in rates.items() if r.rate is not None}
    fields = {"tickers": len(targets), "written": written, "solved_both_sides": solved_both, "solved_one_side": solved_one, "unsolved": len(skipped),
              "unsolved_detail": dict(list(skipped.items())[:30]), "skipped_nonstandard": skipped_nonstandard,
              "skipped_stale": dict(list(skipped_stale.items())[:50]), "skipped_stale_count": len(skipped_stale),
              "rates_used": rates_used, "rates_stored": stored, "rate_fetch_error": rate_fetch_error, "iv_version": IV_SOLVER_VERSION,
              "progress": {"done": len(targets), "of": len(targets)}, "batch": BATCH, "error": None}
    print(f"{STEP_LABEL}: {len(targets)} ticker(s), {written} row(s) written (v{IV_SOLVER_VERSION}), both sides {solved_both}, one side {solved_one}, "
          f"unsolved {len(skipped)}, skipped as nonstandard (an ATM mid under ${MIN_ATM_MID:.2f}) {len(skipped_nonstandard)}, "
          f"refused as stale {len(skipped_stale)}; rates {rates_used}; "
          f"{stored} rate row(s) stored" + (f"; rate fetch failed: {rate_fetch_error}" if rate_fetch_error else ""))
    for k, v in skipped_nonstandard.items():
        print(f"   nonstandard {k}: spot {v['spot']} strike {v['strike']} mids {v['call_mid']}/{v['put_mid']} ({v['expiration']})")
    for k, v in list(skipped.items())[:10]:
        print(f"   {k}: {v}")
    await record_step_fields(STEP_LABEL, fields)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
