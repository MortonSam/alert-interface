"""Nightly: the put-call parity verdict of every active ticker's newest chain from each source (services/options_source), against the
official close of the chain's date, stored as chain_parity:{SYM} = {"courier": verdict, "intrinio": verdict}. The pages read these
(a chain newer than its verdict is checked when first read); validate's chain_parity names every failure.

Usage: python -m app.scripts.check_chain_parity [--symbols=MTD,CHTR]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import options_source as O
from app.services.redact import redact
from app.services.system_metadata_service import set_value
from app.services.write_failures import WriteFailures

STEP_LABEL = "Chain parity (both sources)"
WRITES = WriteFailures(STEP_LABEL)


async def run(argv: list[str]) -> int:
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "")
    async with ScriptSessionLocal() as s:
        symbols = [x.strip().upper() for x in only.split(",") if x.strip()] or \
            list((await s.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
    counts = {src: {"checked": 0, "failed": 0, "provisional": 0} for src in (O.COURIER, O.INTRINIO)}
    failures: dict[str, list[str]] = {O.COURIER: [], O.INTRINIO: []}
    for sym in symbols:
        try:
            async with ScriptSessionLocal() as s:
                out = {}
                for src in (O.COURIER, O.INTRINIO):
                    v = await O.compute_verdict(s, sym, src)
                    if v is None:
                        continue
                    v = {k: v[k] for k in v if k != "fresh"} | {"checked_at": datetime.now(timezone.utc).isoformat()}
                    out[src] = v
                    counts[src]["checked"] += 1
                    counts[src]["provisional"] += bool(v.get("provisional"))
                    if not v.get("ok"):
                        counts[src]["failed"] += 1
                        failures[src].append(f"{sym} {v.get('chain_date')}: {v.get('reason')}")
                await set_value(s, O.VERDICT_KEY.format(sym=sym), json.dumps(out))
                await s.commit()
        except Exception as exc:
            WRITES.note(sym, exc)
            print(f"  {sym}: {redact(exc)[:120]}")
    for src in (O.COURIER, O.INTRINIO):
        c = counts[src]
        print(f"{src}: {c['checked']} chains checked, {c['failed']} fail parity, {c['provisional']} against the courier's post-close price")
        for f in failures[src][:40]:
            print(f"  {f}")
    try:
        from app.services.step_outcomes import record_step_fields
        await record_step_fields(STEP_LABEL, {"counts": counts, "failures": {k: v[:60] for k, v in failures.items()}})
    except Exception:
        pass
    return WRITES.exit_code()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
