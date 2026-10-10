"""Ivy's Discover sentences step (behind DISCOVER_NEWS_ENABLED): after each news run, for every row Discover shows (the top movers and
In the news), write Ivy's sentence (services/ivy_moves) unless one is already stored for the same stories, and store it with its
sources, the check result, the cost and when it was written. A failure is stored too (result "fallback", with the reasons) and logged.
The run's counts go to system_metadata (ivy_moves.RUN_KEY) for validate.

Usage: python -m app.scripts.explain_moves [--force]   (--force runs with the flag off, for a local check)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal
from app.services import ivy_moves as M
from app.services.step_outcomes import record_step_fields
from app.services.system_metadata_service import set_value

_log = logging.getLogger("ivy_moves")


async def run(argv: list[str], now: datetime | None = None) -> int:
    if not (settings.discover_news_enabled or "--force" in argv):
        print("Ivy's Discover sentences: DISCOVER_NEWS_ENABLED is off; nothing written.")
        return 0
    from app.routers.discover_news import build_sections
    t0 = time.time()
    now = now or datetime.now(timezone.utc)
    counts = {"rows": 0, "written": 0, "reused": 0, "passed": 0, "no_news": 0, "fallback": 0, "cost_usd": 0.0}
    async with ScriptSessionLocal() as db:
        extra: dict = {}
        up, down, ranked, change, _suppressed, _session = await build_sections(db, now, extra)
        rows = [(m.symbol, m.name, m.change_pct) for m in up + down] + [(r["symbol"], extra["names"].get(r["symbol"]), change[r["symbol"]]) for r in ranked]
        seen: set[str] = set()
        for sym, name, move in rows:
            if sym in seen or move is None:
                continue
            seen.add(sym)
            counts["rows"] += 1
            inputs = M.input_stories(extra["window"], sym, name, extra["since"])
            if not inputs:
                counts["no_news"] += 1
                continue
            fp = M.fingerprint(sym, inputs)
            row = (await db.execute(text("SELECT result FROM ivy_move_notes WHERE symbol = :s AND fingerprint = :f"), {"s": sym, "f": fp})).first()
            if row:
                counts["reused"] += 1
                counts[row.result] = counts.get(row.result, 0) + 1
                continue
            note = await M.explain(sym, name, move, inputs)
            counts["written"] += 1
            counts[note["result"]] += 1
            counts["cost_usd"] += note["cost_usd"]
            if note["result"] == "fallback":
                _log.warning("ivy sentence fell back: %s %s", sym, json.dumps(note["problems"])[:600])
                print(f"  {sym}: fell back to the headline display ({'; '.join(note['problems'][-1]['reasons'])[:200]})")
            await db.execute(text("""
                INSERT INTO ivy_move_notes (symbol, fingerprint, move_pct, sentence, result, sources, problems, attempts, model, input_tokens,
                                            output_tokens, cost_usd, written_at)
                VALUES (:s, :f, :m, :sentence, :result, CAST(:sources AS jsonb), CAST(:problems AS jsonb), :attempts, :model, :i, :o, :cost, now())
                ON CONFLICT (symbol, fingerprint) DO NOTHING"""),
                {"s": sym, "f": fp, "m": move, "sentence": note["sentence"] if note["result"] == "passed" else None, "result": note["result"],
                 "sources": json.dumps(note["sources"]), "problems": json.dumps(note["problems"]), "attempts": note["attempts"],
                 "model": note["model"], "i": note["input_tokens"], "o": note["output_tokens"], "cost": round(note["cost_usd"], 5)})
            await db.commit()
        counts["cost_usd"] = round(counts["cost_usd"], 4)
        await set_value(db, M.RUN_KEY, json.dumps({**counts, "at": now.isoformat()}))
        await db.commit()
    seconds = round(time.time() - t0, 1)
    print(f"Ivy's Discover sentences: {counts['rows']} rows, {counts['written']} written, {counts['reused']} reused, {counts['passed']} passed, "
          f"{counts['no_news']} no news, {counts['fallback']} fell back, ${counts['cost_usd']:.4f}, {seconds}s")
    await record_step_fields(M.STEP_LABEL, {"exit": 0, "at": datetime.now(timezone.utc).isoformat(), "seconds": seconds, **counts})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
