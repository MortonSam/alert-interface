"""Put back every research note a failed rewrite took down (Sam, 2026-11-10). Until research_note_service kept a served note through
its rewrite, a rewrite's start emptied the row, so a failed rewrite left the stock with no note at all (Nov 5 to 10, 2026: an empty
credit balance failed 168). The old notes survive only in a database backup: restore a Railway backup taken before the rewrite into
a NEW database (never over production), then copy each note back from it.

For every note that is failed now, the backup's row for the same stock is copied back when it was served there (complete, with its
check), with its own written and checked dates, so the page shows the note's real date. Nothing else is touched. Dry run by default.

    python -m app.scripts.restore_notes --from=postgresql://...backup...          # what would come back
    python -m app.scripts.restore_notes --from=postgresql://...backup... --write
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import ScriptSessionLocal

COLUMNS = ("generated_at", "source_filings", "content", "model_used", "input_tokens", "output_tokens", "verification", "verified_at",
           "verification_model", "status", "error", "structured_content", "data_version", "verification_input_tokens",
           "verification_output_tokens", "estimated_cost_usd")


def async_url(url: str) -> str:
    """Pure: a postgres URL for asyncpg."""
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    raise SystemExit("--from must be a postgres URL")


async def run(argv: list[str]) -> int:
    src_url = next((a.split("=", 1)[1] for a in argv if a.startswith("--from=")), None)
    if not src_url:
        raise SystemExit(__doc__)
    write = "--write" in argv
    async with ScriptSessionLocal() as db:
        down = {str(r.ticker_id): r.symbol for r in (await db.execute(text(
            "SELECT n.ticker_id, t.symbol FROM research_notes n JOIN tickers t ON t.id = n.ticker_id WHERE n.status = 'failed'"))).all()}
    engine = create_async_engine(async_url(src_url))
    async with engine.connect() as src:
        rows = (await src.execute(text(f"""SELECT ticker_id, {', '.join(COLUMNS)} FROM research_notes
            WHERE status = 'complete' AND verification IS NOT NULL AND verification::text <> 'null' AND ticker_id = ANY(CAST(:ids AS uuid[]))"""),
            {"ids": list(down)})).mappings().all()
    await engine.dispose()
    back = {str(r["ticker_id"]): r for r in rows}
    print(f"{len(down)} note(s) down after a failed rewrite; {len(back)} served in the backup, {len(down) - len(back)} not")
    for tid, sym in sorted(down.items(), key=lambda x: x[1]):
        r = back.get(tid)
        print(f"  {sym}: " + (f"back, written {r['generated_at']:%Y-%m-%d}" if r else "not in the backup as a served note; stays down"))
    if not write:
        print("dry run: nothing written")
        return 0
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import bindparam
    stmt = text(f"""UPDATE research_notes SET {', '.join(f'{c} = :{c}' for c in COLUMNS)}, updated_at = now()
        WHERE ticker_id = CAST(:tid AS uuid) AND status = 'failed'""").bindparams(
        bindparam("source_filings", type_=JSONB), bindparam("verification", type_=JSONB), bindparam("structured_content", type_=JSONB))
    async with ScriptSessionLocal() as db:
        for tid, r in back.items():
            await db.execute(stmt, {**{c: r[c] for c in COLUMNS}, "tid": tid})
        await db.commit()
    print(f"restored {len(back)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
