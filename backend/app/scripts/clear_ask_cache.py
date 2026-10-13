"""Clear every cached Ask Ivy answer produced before the analyst's voice (services/ask_ivy, CACHE_VERSION 2, 2026-10-12), so a repeated
question gets a fresh answer. The cache key now carries the version, so old answers are never served again by key alone; this script
makes that explicit by blanking the cache_key of every served answer logged before the change, and reports the count. Dry run by
default; --write blanks the keys. Run it against production only on Sam's go.

    python -m app.scripts.clear_ask_cache            # count
    python -m app.scripts.clear_ask_cache --write
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

SERVED = ("verified", "partly_dropped", "fallback", "not_covered", "off_topic", "advice", "declined")


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as s:
        n = (await s.execute(text("SELECT count(*) FROM ask_log WHERE answer IS NOT NULL AND cache_key <> '' AND verdict = ANY(:v)"), {"v": list(SERVED)})).scalar() or 0
        print(f"{n} cached answer(s) from before the change would be cleared")
        if not write:
            print("dry run: nothing written (add --write)")
            return 0
        await s.execute(text("UPDATE ask_log SET cache_key = '' WHERE answer IS NOT NULL AND cache_key <> '' AND verdict = ANY(:v)"), {"v": list(SERVED)})
        await s.commit()
        print(f"cleared {n}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
