"""Nightly: the put/call ratio from the stored Intrinio chains (the serving source), one row per active ticker per chain date.

Before 2026-10-12 the ratio was written only when the courier on Sam's Mac delivered a chain (routers/admin ingest), so it followed the
courier's calendar and went dark when the courier did. Now it is computed from the serving source's nearest expiry after the chain's
date: volume on every put over volume on every call, on the chain as stored (services/chain_quality already removed non-standard
contracts), and stored in put_call_snapshots with basis "volume" and computation_version PUT_CALL_COMPUTATION_VERSION. A side with
fewer than MIN_SIDE_CONTRACTS contracts traded stores a null ratio with the totals (the page says why).

    python -m app.scripts.compute_put_call                 # the nightly step
    python -m app.scripts.compute_put_call --symbols=MU,KO
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.constants import MIN_SIDE_CONTRACTS
from app.database import ScriptSessionLocal
from app.services import chain_store
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Put/call ratio (Intrinio)"
PUT_CALL_COMPUTATION_VERSION = 3    # 3 (2026-10-12): from the serving source's stored chains nightly, not the courier's ingest


def ratio_from(calls: list[dict], puts: list[dict]) -> tuple[float | None, int, int]:
    """Pure: (ratio or None when a side is too thin, put volume, call volume) from a stored chain's sides."""
    put_vol = sum(int(p.get("volume") or 0) for p in puts)
    call_vol = sum(int(c.get("volume") or 0) for c in calls)
    if put_vol < MIN_SIDE_CONTRACTS or call_vol < MIN_SIDE_CONTRACTS:
        return None, put_vol, call_vol
    return round(put_vol / call_vol, 4), put_vol, call_vol


def nearest_expiration(expirations: list[str], chain_date: str) -> str | None:
    """Pure: the first expiry after the chain's date (the front month, the busiest book)."""
    later = sorted(e for e in expirations if e > chain_date)
    return later[0] if later else None


async def run(argv: list[str]) -> int:
    only = {x.strip().upper() for x in next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "").split(",") if x.strip()} or None
    source = chain_store.INTRINIO
    written = thin = no_chain = 0
    dates: dict[str, int] = {}
    errors: list[str] = []
    async with ScriptSessionLocal() as s:
        symbols = list((await s.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
        if only:
            symbols = [x for x in symbols if x in only]
        for sym in symbols:
            try:
                chain_date = await chain_store.get_latest_chain_date(s, sym, source=source)
                exps = await chain_store.get_ingested_expirations(s, sym, source=source)
                exp = nearest_expiration(exps, chain_date) if chain_date else None
                got = await chain_store.get_chain(s, sym, exp, source=source) if exp else None
                if not got or (got[1] or "")[:10] != chain_date:
                    no_chain += 1
                    continue
                chain = got[0]
                ratio, put_vol, call_vol = ratio_from(chain.get("calls") or [], chain.get("puts") or [])
                if ratio is None:
                    thin += 1
                await s.execute(text("""
                    INSERT INTO put_call_snapshots (id, symbol, snapshot_date, ratio, basis, put_total, call_total, expiration_used, computation_version, created_at)
                    VALUES (gen_random_uuid(), :symbol, :d, :ratio, 'volume', :p, :c, :exp, :v, :now)
                    ON CONFLICT (symbol, snapshot_date) DO UPDATE SET ratio = :ratio, put_total = :p, call_total = :c, expiration_used = :exp,
                        computation_version = :v, created_at = :now"""),
                    {"symbol": sym, "d": date.fromisoformat(chain_date), "ratio": ratio, "p": put_vol, "c": call_vol, "exp": exp, "v": PUT_CALL_COMPUTATION_VERSION,
                     "now": datetime.now(timezone.utc)})
                written += 1
                dates[chain_date] = dates.get(chain_date, 0) + 1
            except Exception as exc:
                errors.append(f"{sym}: {str(exc)[:120]}")
        await s.commit()
    print(f"{STEP_LABEL}: {written} ratio(s) written for {len(symbols)} ticker(s) (dates {dates}), {thin} with a side too thin, {no_chain} without a {source} chain, {len(errors)} error(s)", flush=True)
    await record_step_fields(STEP_LABEL, {"written": written, "tickers": len(symbols), "thin": thin, "no_chain": no_chain, "dates": dates, "errors": errors[:20],
                                          "computation_version": PUT_CALL_COMPUTATION_VERSION, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
