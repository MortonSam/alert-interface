"""Nightly: Intrinio's EOD options chains beside the courier's, by security record. Nothing reads them but validate.

Scheduled at 03:05 America/New_York (services/chain_shadow): when the pipeline reaches this step earlier it waits,
and the step outcome names the clock it ran on. For every active ticker with a current security record, one
request lists Intrinio's expirations after the EOD date; the front expiry and every expiration the courier holds
(up to MAX_EXPIRATIONS) are fetched and stored under intrinio_chain:{SYM}:{EXP} with chain_last_trade = the EOD
date, the quote timestamps kept, and the spot from the stored shadow bar of that date. Expired Intrinio chains
are removed. The outcome records requests, tickers, chains, the EOD date, late publications and errors.

Usage
-----
    python -m app.scripts.shadow_option_chains                       # the nightly step (waits for 03:05 New York)
    python -m app.scripts.shadow_option_chains --now --symbols=MU,CAT  # no wait, two tickers
    python -m app.scripts.shadow_option_chains --now --on=2026-10-01   # that session's EOD chains
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.security_record import SecurityRecord
from app.models.ticker import Ticker
from app.services import chain_store
from app.services.chain_shadow import (MAX_WAIT_SECONDS, chain_dates, clock_fields, expected_session, front_expiration, local_now,
                                       to_stored_chain, wait_seconds)
from app.services.intrinio_client import IntrinioAuthError, IntrinioClient
from app.services.security_records import CURRENT
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Options chains (Intrinio)"
MAX_EXPIRATIONS = 5


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def _targets(only: set[str] | None) -> list[dict]:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(
            select(SecurityRecord.symbol, SecurityRecord.id, SecurityRecord.intrinio_security_id, SecurityRecord.intrinio_ticker)
            .join(Ticker, Ticker.symbol == SecurityRecord.symbol)
            .where(Ticker.is_active.is_(True), SecurityRecord.role == CURRENT, SecurityRecord.intrinio_ticker.isnot(None))
            .order_by(SecurityRecord.symbol))).all()
    return [{"symbol": r.symbol, "id": str(r.id), "intrinio_security_id": r.intrinio_security_id, "intrinio_ticker": r.intrinio_ticker}
            for r in rows if not only or r.symbol in only]


async def _spot(symbol: str, on: date) -> float | None:
    async with ScriptSessionLocal() as s:
        return (await s.execute(text("select close from price_bars_shadow where symbol = :s and date = :d"), {"s": symbol, "d": on})).scalar()


async def run(argv: list[str]) -> int:
    now_utc = datetime.now(timezone.utc)
    waited = 0.0
    early_reason = None
    if "--now" not in argv:
        wait = wait_seconds(now_utc)
        if wait > MAX_WAIT_SECONDS:
            early_reason = f"the schedule was {wait / 3600:.1f} h away, more than {MAX_WAIT_SECONDS // 3600} h: not the configured nightly, ran at once"
        elif wait > 0:
            print(f"{STEP_LABEL}: waiting {wait:.0f}s for 03:05 {local_now(now_utc).tzname()} (clock America/New_York)", flush=True)
            await asyncio.sleep(wait)
            waited = wait
            now_utc = datetime.now(timezone.utc)
    on_arg = _arg(argv, "on")
    expected = date.fromisoformat(on_arg) if on_arg else expected_session(local_now(now_utc))
    only = {x.strip().upper() for x in _arg(argv, "symbols").split(",")} if _arg(argv, "symbols") else None
    targets = await _targets(only)
    client = IntrinioClient()
    chains_written = 0
    tickers_with_chains: list[str] = []
    no_options: list[str] = []
    late: dict[str, str] = {}
    no_spot: list[str] = []
    errors: list[str] = []
    eod_dates: dict[str, int] = {}
    try:
        for t in targets:
            sym, tk = t["symbol"], t["intrinio_ticker"]
            try:
                exps = await client.options_expirations_eod(tk, after=expected)
                if not exps:
                    no_options.append(sym)
                    continue
                async with ScriptSessionLocal() as s:
                    courier_exps = await chain_store.get_ingested_expirations(s, sym)
                front = front_expiration(exps, expected.isoformat())
                wanted = [e for e in sorted(set(courier_exps) & set(exps)) if e > expected.isoformat()]
                if front and front not in wanted:
                    wanted = [front] + wanted
                wanted = wanted[:MAX_EXPIRATIONS]
                wrote = 0
                for exp in wanted:
                    contracts = await client.options_chain_eod(tk, exp, expected if on_arg else None)
                    if not contracts:
                        continue
                    dates = chain_dates(contracts)
                    eod = date.fromisoformat(dates[-1]) if dates else expected
                    eod_dates[eod.isoformat()] = eod_dates.get(eod.isoformat(), 0) + 1
                    spot = await _spot(sym, eod)
                    if spot is None and sym not in no_spot:
                        no_spot.append(sym)
                    chain = to_stored_chain(contracts, exp, eod, spot, "price_bars_shadow" if spot is not None else None, t, datetime.now(timezone.utc), expected)
                    if chain["late"]:
                        late[sym] = eod.isoformat()
                    async with ScriptSessionLocal() as s:
                        await chain_store.put_chain(s, sym, exp, chain, chain_store.INTRINIO)
                        await s.commit()
                    wrote += 1
                if wrote:
                    chains_written += wrote
                    tickers_with_chains.append(sym)
            except IntrinioAuthError as exc:
                await record_step_fields(STEP_LABEL, {"error": str(exc)[:200], **clock_fields(now_utc, waited, early_reason)})
                print(f"Intrinio refused the key: {exc}")
                return 1
            except Exception as exc:
                errors.append(f"{sym}: {str(exc)[:120]}")
        async with ScriptSessionLocal() as s:
            removed = await chain_store.delete_expired(s, chain_store.INTRINIO, expected)
            await s.commit()
    finally:
        await client.close()
    fields = {"expected_session": expected.isoformat(), "eod_dates": eod_dates, "tickers": len(targets), "tickers_with_chains": len(tickers_with_chains),
              "chains": chains_written, "no_options": no_options[:50], "no_options_count": len(no_options), "late": late, "no_spot": no_spot[:50],
              "expired_removed": len(removed), "requests": client.request_count, "retries": client.log.retries, "errors": errors[:50], "error": None,
              **clock_fields(now_utc, waited, early_reason)}
    print(f"{STEP_LABEL}: {len(targets)} ticker(s), {len(tickers_with_chains)} with chains, {chains_written} chain(s) for session {expected} "
          f"(EOD dates {eod_dates}), {len(no_options)} without options, {len(late)} late, {len(no_spot)} without a stored spot, "
          f"{len(removed)} expired removed, {client.request_count} request(s), {len(errors)} error(s); clock {fields['clock']} {fields['started_local']} waited {fields['waited_seconds']}s")
    for e in errors[:10]:
        print("   ", e)
    await record_step_fields(STEP_LABEL, fields)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
