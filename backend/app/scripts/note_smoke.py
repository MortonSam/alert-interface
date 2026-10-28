"""A research note end to end for a few stocks: the context, the generation, the stats strip, the text, the verification and the
reader's view, held in memory and never stored (Sam, 2026-10-27, after BNY's notes failed on a withheld field for a week unseen).

The push gate runs it on its test copy for NOTE_SMOKE_GATE (a bank, a large cap, a REIT, a stock under a cash deal and a new listing);
the nightly runs it with production's key for NOTE_SMOKE_NIGHTLY stocks, a different three each night (rotate). Any stock whose
note raised, came back empty or read with exception text fails the run (exit 1): the push is refused, or the nightly's digest names
the step. A note the verifier flags is not a failure here; that is the note checks' verdict, which the outcome records.

    python -m app.scripts.note_smoke --symbols=BNY,NVDA,O,PTC,VYLR      # the gate
    python -m app.scripts.note_smoke --rotate=3                          # the nightly step
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services.redact import redact

STEP_LABEL = "Research note check"
NOTE_SMOKE_GATE = ("BNY", "NVDA", "O", "PTC", "VYLR")
NOTE_SMOKE_NIGHTLY = 3
STOCK_SECONDS = 420                 # one stock's generation and verification, both bounded by MODEL_TIMEOUT_SECONDS
RAW = re.compile(r"Traceback|NoneType|object has no attribute|KeyError|TypeError|ValueError|AttributeError")


def rotation(symbols: list[str], n: int, on: date) -> list[str]:
    """Pure: n of the symbols, a different n each day, every symbol in turn."""
    if not symbols:
        return []
    ordered = sorted(symbols)
    start = (on.toordinal() * n) % len(ordered)
    return [ordered[(start + i) % len(ordered)] for i in range(min(n, len(ordered)))]


async def one(symbol: str) -> dict:
    """Generate, verify and read one stock's note in memory: {symbol, ok, verdict, cost_usd, seconds, error}."""
    from app.routers.research_notes import _note_for_reader
    from app.services.note_claims import lost
    from app.services import research_note_service as R
    from app.services.research_cost import estimate_cost_usd
    t0 = time.monotonic()
    out = {"symbol": symbol, "ok": False, "verdict": None, "cost_usd": 0.0, "seconds": None, "error": None}
    try:
        async with AsyncSessionLocal() as db:
            ticker = await R._resolve_ticker(db, None, symbol)
            filing, sections, reactions = await R._fetch_context(db, ticker)
            prompt = R._build_generation_prompt(ticker, filing, sections, reactions, await R.merger_context(db, ticker.symbol))
            structured, gen = await R._generate_structured(prompt, ticker.symbol)
            structured["stats"] = R._build_stats_object(ticker, reactions)
            structured["financials"] = await R._fetch_financials(symbol)
            content = R._serialize_structured_note(structured, ticker)
            verification, ver_model, ver_in, ver_out = await R._run_verification(content, filing, sections, reactions, ticker)
            out["cost_usd"] = round((estimate_cost_usd(gen["model_used"], gen["input_tokens"], gen["output_tokens"]) or 0.0)
                                    + (estimate_cost_usd(ver_model, ver_in, ver_out) or 0.0), 4)
            now = datetime.now(timezone.utc)
            from app.config import settings
            from app.services.prod_key_guard import is_production_db
            if is_production_db(settings.database_url):      # production's spend counts toward its daily AI cap; a test copy's does not
                await R._add_to_daily_spend(db, out["cost_usd"], now)
                await db.commit()
        note = SimpleNamespace(id=uuid.uuid4(), ticker_id=ticker.id, generated_at=now, source_filings=[], content=content,
                               model_used=gen["model_used"], input_tokens=gen["input_tokens"], output_tokens=gen["output_tokens"],
                               structured_content=structured, verification=verification, verified_at=now, verification_model=ver_model,
                               status="complete", error=None, created_at=now, updated_at=now)
        summary = (verification or {}).get("summary") or {}
        out["verdict"] = {k: summary.get(k) for k in ("supported", "unsupported", "contradicted")}
        out["lost"] = lost(structured, verification)        # sentences the served note leaves out
        held = R.check_outcome(structured, verification)
        if held:                                            # the real path writes such a note again once (run_research_note_background)
            out["ok"], out["error"] = True, None
            out["held"] = held
            out["seconds"] = round(time.monotonic() - t0, 1)
            return out
        read = _note_for_reader(note, admin=False)          # what a visitor would be served
        if not (read.content or "").strip():
            out["error"] = "the served note is empty"
        elif RAW.search(read.content):
            out["error"] = "the served note carries exception text"
        else:
            out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {redact(exc)}"[:300]
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


async def run(argv: list[str]) -> int:
    from app.services.prod_key_guard import check_production_key
    check_production_key()                         # production's database only with production's key
    syms = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    rotate = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--rotate=")), None)
    if syms:
        symbols = [s.strip().upper() for s in syms.split(",") if s.strip()]
    else:
        async with AsyncSessionLocal() as db:
            active = list((await db.execute(text("SELECT symbol FROM tickers WHERE is_active"))).scalars().all())
        symbols = rotation(active, rotate or NOTE_SMOKE_NIGHTLY, date.today())
    results = await asyncio.gather(*(asyncio.wait_for(one(s), STOCK_SECONDS) for s in symbols), return_exceptions=True)
    rows = [r if isinstance(r, dict) else {"symbol": s, "ok": False, "error": f"timed out after {STOCK_SECONDS}s"} for s, r in zip(symbols, results)]
    for r in rows:
        print(f"  {r['symbol']}: {'ok' if r['ok'] else 'FAILED'}" + (f", verifier {r.get('verdict')}" if r.get("verdict") else "")
              + (f", ${r.get('cost_usd', 0):.3f}, {r.get('seconds')}s" if r.get("seconds") else "") + (f": {r['error']}" if r.get("error") else ""), flush=True)
    failed = [r for r in rows if not r["ok"]]
    print(f"{STEP_LABEL}: {len(rows) - len(failed)} of {len(rows)} note(s) generated, verified and served", flush=True)
    if not syms:                                   # the nightly records its outcome (the gate's run is the gate's own)
        from app.services.step_outcomes import record_step_fields
        await record_step_fields(STEP_LABEL, {"stocks": rows, "failed": [f"{r['symbol']}: {r['error']}" for r in failed],
                                              "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4), "error": None})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
