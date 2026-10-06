"""Fetch Intrinio company profiles for every active ticker whose profile is missing or older than PROFILE_MAX_AGE_DAYS,
store them dated (company_profiles), and take shares outstanding and the market cap from the Finnhub profile for the
same tickers (tickers.shares_outstanding, dated). The nightly records and profile-refresh steps do the same top-ups;
this is the one-off to fill them now.

    python -m app.scripts.seed_company_profiles
    python -m app.scripts.seed_company_profiles --all                 # refresh every active ticker regardless of age
    python -m app.scripts.seed_company_profiles --symbols=MU,MSFT     # just these
    python -m app.scripts.seed_company_profiles --all --shares-only   # share counts and market caps from Finnhub only
"""
from __future__ import annotations
from app.services.redact import redact

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.build_security_records import PROFILE_MAX_AGE_DAYS, store_profile
from app.services.intrinio_client import IntrinioClient
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Company profiles (Intrinio)"


async def store_shares(symbol: str, profile: dict) -> bool:
    """tickers.shares_outstanding (and the market cap) from a Finnhub profile2 payload, dated now; False when it had none."""
    shares_m = profile.get("shareOutstanding")
    mcap_m = profile.get("marketCapitalization")
    if not shares_m or float(shares_m) <= 0:
        return False
    async with ScriptSessionLocal() as s:
        await s.execute(text("""
            UPDATE tickers SET shares_outstanding = :sh, shares_as_of = :at,
                   market_cap = COALESCE(:mc, market_cap), market_cap_updated_at = CASE WHEN :mc IS NULL THEN market_cap_updated_at ELSE :at END
            WHERE symbol = :s"""), {"sh": int(float(shares_m) * 1_000_000), "mc": int(float(mcap_m) * 1_000_000) if mcap_m and float(mcap_m) > 0 else None,
                                    "at": datetime.now(timezone.utc), "s": symbol})
        await s.commit()
    return True


async def run(argv: list[str]) -> int:
    refresh_all = "--all" in argv
    shares_only = "--shares-only" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    only_set = {x.strip().upper() for x in only.split(",")} if only else None
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT t.symbol, p.fetched_at, t.shares_as_of FROM tickers t LEFT JOIN company_profiles p ON p.symbol = t.symbol
            WHERE t.is_active ORDER BY t.symbol"""))).all()
    if only_set:
        rows = [r for r in rows if r[0] in only_set]
    due_profile = [] if shares_only else [sym for sym, at, _ in rows if refresh_all or at is None or (now - at).days >= PROFILE_MAX_AGE_DAYS]
    due_shares = [sym for sym, _, at in rows if refresh_all or at is None or (now - at).days >= PROFILE_MAX_AGE_DAYS]
    print(f"{STEP_LABEL}: {len(rows)} ticker(s), {len(due_profile)} profiles and {len(due_shares)} share counts to fetch", flush=True)
    client = IntrinioClient()
    from app.services.finnhub_client import FinnhubClient
    finnhub = FinnhubClient()
    done, shares_done, failed = [], [], []
    try:
        for sym in due_profile:
            try:
                body = await client._get(f"/companies/{sym}", {})
                async with ScriptSessionLocal() as s:
                    await store_profile(s, sym, body, datetime.now(timezone.utc))
                    await s.commit()
                done.append(sym)
            except Exception as exc:
                failed.append(f"{sym} (Intrinio): {redact(exc)[:80]}")
                print(f"  [WARN] {sym}: {redact(exc)}", flush=True)
        for sym in due_shares:
            try:
                if await store_shares(sym, await finnhub.get_profile2(sym)):
                    shares_done.append(sym)
            except Exception as exc:
                failed.append(f"{sym} (Finnhub): {redact(exc)[:80]}")
                print(f"  [WARN] {sym}: {redact(exc)}", flush=True)
    finally:
        await client.close()
        await finnhub.close()
    print(f"  stored {len(done)} profile(s) and {len(shares_done)} share count(s), {len(failed)} failed; {client.request_count} Intrinio request(s)")
    from app.services.finnhub_client import finnhub_stats
    await record_step_fields(STEP_LABEL, {"tickers": len(rows), "profiles": len(done), "shares": len(shares_done), "failed": failed[:40], "finnhub": finnhub_stats(), "error": None})
    return 0 if (done or shares_done) or not (due_profile or due_shares) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
