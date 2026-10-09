"""Nightly: Intrinio's EOD options chains beside the courier's, by security record. Nothing reads them but validate.

Scheduled at 03:05 America/New_York (services/chain_shadow): when the pipeline reaches this step earlier it waits,
and the step outcome names the clock it ran on. For every active ticker with a current security record, one
request lists Intrinio's expirations after the EOD date; the front expiry, and for a ticker reporting within
EARNINGS_WINDOW_DAYS the nearest expiry that captures each report (after the report day, or on it for a before-open report) and the last
one that does not, are always fetched,
then the expirations the courier holds up to MAX_EXPIRATIONS in all (services/chain_shadow.wanted_expirations). They are fetched and stored under intrinio_chain:{SYM}:{EXP} with chain_last_trade = the EOD
date, the quote timestamps kept, and the spot from the stored shadow bar of that date. Expired Intrinio chains
are removed. As each ticker's front-expiry chain is stored it is compared with the courier's chain for the same session
(services/chain_shadow.compare_front) and the night's figures go to chain_shadow:{date} and the outcome, which validate's
chain_shadow check judges. Courier expirations and the session's closes are read in one query each up front. The outcome
records requests, tickers, chains, the EOD date, late publications, the comparison and errors.

Usage
-----
    python -m app.scripts.shadow_option_chains                       # the nightly step (waits for 03:05 New York)
    python -m app.scripts.shadow_option_chains --now --symbols=MU,CAT  # no wait, two tickers
    python -m app.scripts.shadow_option_chains --now --on=2026-10-01   # that session's EOD chains
"""
from __future__ import annotations
from app.services.redact import redact

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.security_record import SecurityRecord
from app.models.ticker import Ticker
from app.services import chain_store
from app.services.chain_shadow import (EARNINGS_WINDOW_DAYS, MAX_WAIT_SECONDS, PER_TICKER_COLUMNS, chain_dates, clock_fields, compare_front,
                                       expected_session, front_expiration, local_now, night_totals, to_stored_chain, wait_seconds,
                                       wanted_expirations)
from app.services.system_metadata_service import set_value
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


async def _spots_on(symbols: list[str], on: date) -> dict[str, float]:
    """Every symbol's stored close for the session, one query."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("select symbol, close from price_bars_shadow where date = :d and symbol = any(:s)"), {"d": on, "s": symbols})).all()
    return {r.symbol: float(r.close) for r in rows if r.close is not None}


async def _courier_index() -> dict[str, dict[str, str]]:
    """{symbol: {expiration: chain_last_trade}} for every courier chain, dates extracted server-side: one query."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT key, value::json->>'chain_last_trade' FROM system_metadata WHERE key LIKE 'chain:%'"))).all()
    out: dict[str, dict[str, str]] = {}
    for key, d in rows:
        parts = key.split(":")
        if len(parts) == 3:
            out.setdefault(parts[1], {})[parts[2]] = str(d)[:10] if d else ""
    return out


async def _earnings_dates(on: date) -> dict[str, list[tuple[str, str | None]]]:
    """{symbol: [(earnings date, report timing)]} for active tickers reporting from the session through EARNINGS_WINDOW_DAYS
    after it: one query."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT DISTINCT t.symbol, e.event_date, e.report_timing FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE t.is_active AND e.event_type = 'earnings' AND e.event_date >= :a AND e.event_date <= :b"""),
            {"a": on, "b": on + timedelta(days=EARNINGS_WINDOW_DAYS)})).all()
    out: dict[str, list[tuple[str, str | None]]] = {}
    for sym, d, timing in rows:
        out.setdefault(sym, []).append((d.isoformat(), timing))
    return out


async def record_night(chain_date: str, per_ticker: dict[str, dict], missing_intrinio: list[str]) -> dict:
    """Store the night (chain_shadow:{date}: totals and per-ticker figures) and put the compact figures in the step outcome."""
    totals = night_totals(chain_date, per_ticker, missing_intrinio)
    async with ScriptSessionLocal() as s:
        await set_value(s, f"chain_shadow:{chain_date}", json.dumps({"totals": totals, "per_ticker": per_ticker}))
        await s.commit()
    compact = {sym: [f.get(c) if c != "courier_only_strikes" else len(f[c]) for c in PER_TICKER_COLUMNS] for sym, f in per_ticker.items()}
    await record_step_fields(STEP_LABEL, {"comparison": {"totals": totals, "per_ticker_columns": PER_TICKER_COLUMNS, "per_ticker": compact}})
    return totals


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
    courier = await _courier_index()                                     # one query: every courier chain's expiry and date
    spots = await _spots_on([t["symbol"] for t in targets], expected)   # one query: every stored close for the session
    earnings = await _earnings_dates(expected)                           # one query: who reports in the window, and when
    client = IntrinioClient()
    chains_written = 0
    tickers_with_chains: list[str] = []
    no_options: list[str] = []
    late: dict[str, str] = {}
    no_spot: list[str] = []
    errors: list[str] = []
    eod_dates: dict[str, int] = {}
    per_ticker: dict[str, dict] = {}        # the night's front-expiry comparison with the courier
    try:
        for t in targets:
            sym, tk = t["symbol"], t["intrinio_ticker"]
            try:
                exps = await client.options_expirations_eod(tk, after=expected)
                if not exps:
                    no_options.append(sym)
                    continue
                wanted = wanted_expirations(exps, expected.isoformat(), sorted(courier.get(sym, {})), earnings.get(sym, []), MAX_EXPIRATIONS)
                wrote = 0
                stored_chains: dict[str, dict] = {}
                for exp in wanted:
                    contracts = await client.options_chain_eod(tk, exp, expected if on_arg else None)
                    if not contracts:
                        continue
                    dates = chain_dates(contracts)
                    eod = date.fromisoformat(dates[-1]) if dates else expected
                    eod_dates[eod.isoformat()] = eod_dates.get(eod.isoformat(), 0) + 1
                    spot = spots.get(sym) if eod == expected else await _spot(sym, eod)
                    if spot is None and sym not in no_spot:
                        no_spot.append(sym)
                    chain = to_stored_chain(contracts, exp, eod, spot, "price_bars_shadow" if spot is not None else None, t, datetime.now(timezone.utc), expected)
                    if chain["late"]:
                        late[sym] = eod.isoformat()
                    async with ScriptSessionLocal() as s:
                        await chain_store.put_chain(s, sym, exp, chain, chain_store.INTRINIO)
                        await s.commit()
                    stored_chains[exp] = chain
                    wrote += 1
                if wrote:
                    chains_written += wrote
                    tickers_with_chains.append(sym)
                # the night's comparison: the courier's front expiry for this session, against the Intrinio chain just stored
                cfront = front_expiration([e for e, d in courier.get(sym, {}).items() if d == expected.isoformat()], expected.isoformat())
                if cfront and cfront in stored_chains and stored_chains[cfront]["chain_last_trade"] == expected.isoformat():
                    async with ScriptSessionLocal() as s:
                        got = await chain_store.get_chain(s, sym, cfront, source=chain_store.COURIER)
                    if got:
                        per_ticker[sym] = compare_front(got[0], stored_chains[cfront])
            except IntrinioAuthError as exc:
                await record_step_fields(STEP_LABEL, {"error": redact(exc)[:200], **clock_fields(now_utc, waited, early_reason)})
                print(f"Intrinio refused the key: {redact(exc)}")
                return 1
            except Exception as exc:
                errors.append(f"{sym}: {redact(exc)[:120]}")
        async with ScriptSessionLocal() as s:
            removed = await chain_store.delete_expired(s, chain_store.INTRINIO, expected)
            await s.commit()
    finally:
        await client.close()
    # tickers the courier priced for this session that got no Intrinio chain tonight
    missing_intrinio = sorted(sym for sym, exps in courier.items() if expected.isoformat() in exps.values()
                              and sym not in tickers_with_chains and (not only or sym in only))
    totals = await record_night(expected.isoformat(), per_ticker, missing_intrinio) if (per_ticker or missing_intrinio) else None
    fields = {"expected_session": expected.isoformat(), "eod_dates": eod_dates, "tickers": len(targets), "tickers_with_chains": len(tickers_with_chains),
              "compared": len(per_ticker), "missing_intrinio": len(missing_intrinio),
              "chains": chains_written, "no_options": no_options[:50], "no_options_count": len(no_options), "late": late, "no_spot": no_spot[:50],
              "expired_removed": len(removed), "requests": client.request_count, "retries": client.log.retries, "errors": errors[:50], "error": None,
              **clock_fields(now_utc, waited, early_reason)}
    print(f"{STEP_LABEL}: {len(targets)} ticker(s), {len(tickers_with_chains)} with chains, {chains_written} chain(s) for session {expected} "
          f"(EOD dates {eod_dates}), {len(no_options)} without options, {len(late)} late, {len(no_spot)} without a stored spot, "
          f"{len(removed)} expired removed, {client.request_count} request(s), {len(errors)} error(s); compared {len(per_ticker)} ticker(s) with the courier, "
          f"{len(missing_intrinio)} courier ticker(s) without an Intrinio chain; clock {fields['clock']} {fields['started_local']} waited {fields['waited_seconds']}s")
    for e in errors[:10]:
        print("   ", e)
    await record_step_fields(STEP_LABEL, fields)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
