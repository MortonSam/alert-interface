"""Nightly: the in-house ATM implied volatility from Intrinio's stored chains, written beside the courier rows, served nowhere.

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

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.iv_history import SOLVER_SOURCE
from app.models.system_metadata import SystemMetadata
from app.services.iv_solver import IV_SOLVER_VERSION, MIN_ATM_MID, choose_expiration, nonstandard_mids, solve_atm
from app.services.rates import fetch_series, rate_on, store_rates
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "ATM IV (solver)"
RATE_FETCH_SINCE_DAYS = 30


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def _intrinio_chains(only: set[str] | None) -> dict[str, dict[str, dict]]:
    """{symbol: {expiration: chain}} from the stored Intrinio chains."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(select(SystemMetadata.key, SystemMetadata.value).where(SystemMetadata.key.like("intrinio_chain:%")))).all()
    out: dict[str, dict[str, dict]] = {}
    for k, v in rows:
        parts = k.split(":")
        if len(parts) != 3 or (only and parts[1] not in only):
            continue
        try:
            out.setdefault(parts[1], {})[parts[2]] = json.loads(v)
        except (ValueError, TypeError):
            continue
    return out


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
    chains = await _intrinio_chains(only)
    if on_arg:
        chains = {sym: {e: c for e, c in exps.items() if str(c.get("chain_last_trade"))[:10] == on_arg} for sym, exps in chains.items()}
        chains = {sym: exps for sym, exps in chains.items() if exps}
    written = 0
    solved_both = solved_one = 0
    skipped: dict[str, str] = {}
    skipped_nonstandard: dict[str, dict] = {}
    rates_used: dict[str, str] = {}
    for sym in sorted(chains):
        exps = chains[sym]
        chain_date = date.fromisoformat(str(next(iter(exps.values())).get("chain_last_trade"))[:10])
        async with ScriptSessionLocal() as s:
            r = await rate_on(s, chain_date)
        if r.rate is None:
            await record_step_fields(STEP_LABEL, {"error": f"no rate: {r.reason}" + (f"; fetch failed: {rate_fetch_error}" if rate_fetch_error else ""),
                                                  "rates_stored": stored, "written": written})
            print(f"{STEP_LABEL}: failed closed, {r.reason}" + (f" (fetch: {rate_fetch_error})" if rate_fetch_error else ""))
            return 1
        rates_used[chain_date.isoformat()] = f"{r.rate:.4%} ({r.rate_date.isoformat()})"
        exp = choose_expiration(list(exps), chain_date)
        chain = exps[exp]
        spot = chain.get("underlying_price")
        if not spot:
            skipped[sym] = "no stored close for the chain date"
            continue
        a = solve_atm(chain, float(spot), chain_date, date.fromisoformat(exp), r.rate)
        if nonstandard_mids(a.call_mid, a.put_mid):
            # no row: a solved number from a penny quote would be a wrong IV, and iv_solver_band is for real solves.
            # A row an earlier run wrote for this ticker and date is removed, so a rerun leaves nothing behind.
            skipped_nonstandard[sym] = {"spot": float(spot), "strike": a.strike, "call_mid": round(a.call_mid, 4) if a.call_mid is not None else None,
                                        "put_mid": round(a.put_mid, 4) if a.put_mid is not None else None, "expiration": exp, "floor": MIN_ATM_MID}
            async with ScriptSessionLocal() as s:
                await s.execute(text("DELETE FROM iv_history WHERE symbol = :s AND date = :d AND iv_source = :src"),
                                {"s": sym, "d": chain_date, "src": SOLVER_SOURCE})
                await s.commit()
            continue
        async with ScriptSessionLocal() as s:
            await s.execute(UPSERT, {
                "symbol": sym, "date": chain_date, "iv_source": SOLVER_SOURCE, "iv_version": IV_SOLVER_VERSION, "expiration": date.fromisoformat(exp),
                "atm_strike": a.strike, "current_price": float(spot), "atm_iv": a.atm_iv, "atm_iv_reason": a.reason,
                "atm_call_mid": a.call_mid, "atm_put_mid": a.put_mid, "solved_call_iv": a.call.iv, "solved_put_iv": a.put.iv,
                "vendor_call_iv": a.vendor_call_iv, "vendor_put_iv": a.vendor_put_iv, "vendor_iv": a.vendor_iv,
                "rate": r.rate, "rate_date": r.rate_date, "days_to_expiry": a.days,
            })
            await s.commit()
        written += 1
        n = sum(1 for x in (a.call, a.put) if x.iv is not None)
        solved_both += n == 2
        solved_one += n == 1
        if n == 0:
            skipped[sym] = a.reason or "unsolved"
    fields = {"tickers": len(chains), "written": written, "solved_both_sides": solved_both, "solved_one_side": solved_one, "unsolved": len(skipped),
              "unsolved_detail": dict(list(skipped.items())[:30]), "skipped_nonstandard": skipped_nonstandard,
              "rates_used": rates_used, "rates_stored": stored,
              "rate_fetch_error": rate_fetch_error, "iv_version": IV_SOLVER_VERSION, "error": None}
    print(f"{STEP_LABEL}: {len(chains)} ticker(s), {written} row(s) written (v{IV_SOLVER_VERSION}), both sides {solved_both}, one side {solved_one}, "
          f"unsolved {len(skipped)}, skipped as nonstandard (an ATM mid under ${MIN_ATM_MID:.2f}) {len(skipped_nonstandard)}; rates {rates_used}; "
          f"{stored} rate row(s) stored" + (f"; rate fetch failed: {rate_fetch_error}" if rate_fetch_error else ""))
    for k, v in skipped_nonstandard.items():
        print(f"   nonstandard {k}: spot {v['spot']} strike {v['strike']} mids {v['call_mid']}/{v['put_mid']} ({v['expiration']})")
    for k, v in list(skipped.items())[:10]:
        print(f"   {k}: {v}")
    await record_step_fields(STEP_LABEL, fields)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
