"""Fetch Intrinio company profiles for every active ticker whose profile is missing or older than PROFILE_MAX_AGE_DAYS,
and store them dated (company_profiles). The nightly records step does the same top-up; this is the one-off to fill
them now.

    python -m app.scripts.seed_company_profiles
    python -m app.scripts.seed_company_profiles --all        # refresh every active ticker regardless of age
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.build_security_records import PROFILE_MAX_AGE_DAYS, store_profile
from app.services.intrinio_client import IntrinioClient
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Company profiles (Intrinio)"


async def run(argv: list[str]) -> int:
    refresh_all = "--all" in argv
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT t.symbol, p.fetched_at FROM tickers t LEFT JOIN company_profiles p ON p.symbol = t.symbol
            WHERE t.is_active ORDER BY t.symbol"""))).all()
    due = [sym for sym, at in rows if refresh_all or at is None or (now - at).days >= PROFILE_MAX_AGE_DAYS]
    print(f"{STEP_LABEL}: {len(rows)} active tickers, {len(due)} to fetch", flush=True)
    client = IntrinioClient()
    done, failed = [], []
    try:
        for sym in due:
            try:
                body = await client._get(f"/companies/{sym}", {})
                async with ScriptSessionLocal() as s:
                    await store_profile(s, sym, body, datetime.now(timezone.utc))
                    await s.commit()
                done.append(sym)
            except Exception as exc:
                failed.append(f"{sym}: {str(exc)[:80]}")
                print(f"  [WARN] {sym}: {exc}", flush=True)
    finally:
        await client.close()
    print(f"  stored {len(done)} profile(s), {len(failed)} failed; {client.request_count} request(s)")
    await record_step_fields(STEP_LABEL, {"active": len(rows), "fetched": len(done), "failed": failed[:40], "error": None})
    return 0 if done or not due else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
