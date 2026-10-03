"""Resolve every active ticker to its Intrinio security record, by id, and keep the map fresh.

For each active ticker: one request to /securities/{ticker}; the current row is written from it, the
predecessor rows, stored_history rows and delistings come from
services/security_records (data); a delisted ticker is marked inactive here, its rows kept. Every refresh also records what Intrinio returned (figi_seen,
last_price_date, checked_at) on the current row, which the validate checks security_record_coverage
and figi_change read without touching the network.

Dry run by default: prints what it would write. --write applies. The nightly runs it with --write.

Usage
-----
    python -m app.scripts.build_security_records
    python -m app.scripts.build_security_records --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.security_record import SecurityRecord
from app.models.ticker import Ticker
from app.services.intrinio_client import IntrinioAuthError, IntrinioClient
from app.services.price_bars_shadow import BENCHMARKS
from app.services.security_records import CURRENT, DELISTED, Record, plan_records
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Security records (Intrinio)"


async def upsert(session, rows: list[Record], seen: dict) -> tuple[int, int, bool]:
    """Write a symbol's rows. Returns (inserted, updated, figi_changed)."""
    inserted = updated = 0
    changed = False
    existing = {r.valid_from: r for r in (await session.execute(
        select(SecurityRecord).where(SecurityRecord.symbol == rows[0].symbol))).scalars().all()}
    now = datetime.now(timezone.utc)
    for r in rows:
        row = existing.get(r.valid_from)
        if row is None:
            row = SecurityRecord(symbol=r.symbol, valid_from=r.valid_from)
            session.add(row)
            inserted += 1
        else:
            updated += 1
        if row.role == CURRENT and row.figi and r.figi and row.figi != r.figi:
            changed = True          # Intrinio moved the ticker to a new record: the check reports it, the stored FIGI stays
        row.intrinio_security_id = r.intrinio_security_id
        row.composite_figi = r.composite_figi
        row.name = r.name
        row.valid_to = r.valid_to
        row.role = r.role
        row.source = r.source
        if row.figi is None:
            row.figi = r.figi
        if r.role == CURRENT:
            row.figi_seen = seen.get("figi")
            lp = seen.get("last_stock_price")
            row.last_price_date = date.fromisoformat(lp) if isinstance(lp, str) else lp
            row.checked_at = now
    return inserted, updated, changed


async def apply_delistings(session, delisted: dict[str, dict] = DELISTED) -> list[str]:
    """Mark each delisted ticker inactive (rows kept; lists and detail routes hide inactive tickers at read time).
    Returns the symbols flipped by this call."""
    rows = (await session.execute(select(Ticker).where(Ticker.symbol.in_(list(delisted)), Ticker.is_active.is_(True)))).scalars().all()
    for t in rows:
        t.is_active = False
        print(f"  {t.symbol}: inactive; last session {delisted[t.symbol]['last_trade'].isoformat()}; {delisted[t.symbol]['note']}", flush=True)
    return sorted(t.symbol for t in rows)


async def main(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as session:
        symbols = list((await session.execute(select(Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    symbols = sorted(set(symbols) | set(BENCHMARKS) | set(DELISTED))   # SPY gives the seeder its session calendar; delisted rows stay resolvable
    client = IntrinioClient()
    resolved: list[str] = []
    missing: list[str] = []
    figi_changes: list[str] = []
    inserted = updated = 0
    try:
        for sym in symbols:
            try:
                current = await client._get(f"/securities/{sym}", {})
            except IntrinioAuthError as exc:
                print(f"  Intrinio refused the key: {exc}", flush=True)
                await record_step_fields(STEP_LABEL, {"error": str(exc)[:200], "resolved": 0})
                return 1
            except Exception as exc:
                missing.append(f"{sym}: {exc}")
                continue
            if not current or not current.get("id"):
                missing.append(f"{sym}: no record")
                continue
            rows = plan_records(sym, current)
            resolved.append(sym)
            if write:
                async with ScriptSessionLocal() as session:
                    ins, upd, changed = await upsert(session, rows, current)
                    await session.commit()
                inserted += ins
                updated += upd
                if changed:
                    figi_changes.append(sym)
            else:
                for r in rows:
                    print(f"  {sym:6} {r.role:14} {r.intrinio_security_id or '-':12} {r.figi or '-':13} {r.valid_from.isoformat()}..{r.valid_to.isoformat() if r.valid_to else 'open'}")
    finally:
        await client.close()
    print(f"\n{'─' * 60}\n  {'written' if write else 'dry run'}: {len(resolved)} resolved, {len(missing)} missing, "
          f"{inserted} inserted, {updated} updated, {len(figi_changes)} FIGI change(s); {client.request_count} request(s)\n{'─' * 60}")
    for m in missing[:20]:
        print("   missing:", m)
    deactivated: list[str] = []
    if write:
        async with ScriptSessionLocal() as session:
            deactivated = await apply_delistings(session)
            await session.commit()
        await record_step_fields(STEP_LABEL, {"resolved": len(resolved), "missing": missing[:50], "inserted": inserted, "updated": updated,
                                              "figi_changes": figi_changes, "requests": client.request_count,
                                              "delisted": {sym: d["last_trade"].isoformat() for sym, d in DELISTED.items()},
                                              "deactivated_this_run": deactivated, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
