"""Nightly: Intrinio daily bars into price_bars_shadow, by security record id, incrementally.

For every symbol in security_records (the active tickers and the SPY benchmark), each Intrinio record is fetched
for the days it still lacks (services/price_bars_shadow.plan_fetches): the whole stored window on the first run,
then from a few days before the last stored bar. Rows upsert on (symbol, date). The step outcome records
requests, symbols, bars written and errors; the refresh runner records the exit.

Usage
-----
    python -m app.scripts.shadow_price_bars            # the nightly step
    python -m app.scripts.shadow_price_bars --plan     # print the fetch plan, no requests, no writes
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.database import ScriptSessionLocal
from app.models.price_bar_shadow import PriceBarShadow
from app.models.security_record import SecurityRecord
from app.services.intrinio_client import IntrinioAuthError, IntrinioClient
from app.services.price_bars_shadow import Fetch, plan_fetches
from app.services.security_records import Record
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Price bars shadow (Intrinio)"
BATCH = 5000


def _rows(fetch: Fetch, bars: list[dict], record_id, now: datetime) -> list[dict]:
    out = []
    for b in bars:
        d = date.fromisoformat(b["date"][:10])
        if not (fetch.start <= d <= fetch.end):
            continue
        out.append({"symbol": fetch.symbol, "date": d, "security_record_id": record_id, "intrinio_security_id": fetch.record.intrinio_security_id,
                    "open": b.get("open"), "high": b.get("high"), "low": b.get("low"), "close": b.get("close"),
                    "volume": int(b["volume"]) if b.get("volume") is not None else None,
                    "adj_open": b.get("adj_open"), "adj_high": b.get("adj_high"), "adj_low": b.get("adj_low"), "adj_close": b.get("adj_close"),
                    "adj_volume": int(b["adj_volume"]) if b.get("adj_volume") is not None else None,
                    "factor": b.get("factor") if b.get("factor") is not None else 1.0,
                    "split_ratio": b.get("split_ratio") if b.get("split_ratio") is not None else 1.0,
                    "dividend": b.get("dividend") or 0.0, "fetched_at": now})
    return out


async def _upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    async with ScriptSessionLocal() as s:
        for i in range(0, len(rows), BATCH):
            stmt = insert(PriceBarShadow).values(rows[i:i + BATCH])
            update = {c: getattr(stmt.excluded, c) for c in rows[0] if c not in ("symbol", "date")}
            await s.execute(stmt.on_conflict_do_update(constraint="pk_price_bars_shadow", set_=update))
        await s.commit()
    return len(rows)


async def load_plan(today: date) -> tuple[list[Fetch], dict]:
    async with ScriptSessionLocal() as s:
        recs = (await s.execute(select(SecurityRecord))).scalars().all()
        last = dict((await s.execute(select(PriceBarShadow.symbol, func.max(PriceBarShadow.date)).group_by(PriceBarShadow.symbol))).all())
    by: dict[str, list[Record]] = {}
    ids: dict[tuple[str, date], object] = {}
    for r in recs:
        by.setdefault(r.symbol, []).append(Record(r.symbol, r.intrinio_security_id, r.figi, r.composite_figi, r.name, r.valid_from, r.valid_to, r.role, r.source))
        ids[(r.symbol, r.valid_from)] = r.id
    return plan_fetches(by, last, today), ids


async def main(argv: list[str]) -> int:
    today = date.today()
    fetches, ids = await load_plan(today)
    if "--plan" in argv:
        for f in fetches:
            print(f"  {f.symbol:6} {f.record.role:12} {f.record.intrinio_security_id:12} {f.start}..{f.end}")
        print(f"\n{len(fetches)} fetch(es) over {len({f.symbol for f in fetches})} symbol(s)")
        return 0
    client = IntrinioClient()
    now = datetime.now(timezone.utc)
    written = 0
    symbols: set[str] = set()
    errors: list[str] = []
    try:
        for f in fetches:
            try:
                bars = await client.daily_prices(f.record.intrinio_security_id, f.start, f.end)
            except IntrinioAuthError as exc:
                await record_step_fields(STEP_LABEL, {"error": str(exc)[:200], "requests": client.request_count, "bars": written})
                print(f"Intrinio refused the key: {exc}")
                return 1
            except Exception as exc:
                errors.append(f"{f.symbol} {f.record.intrinio_security_id}: {str(exc)[:120]}")
                continue
            n = await _upsert(_rows(f, bars, ids[(f.symbol, f.record.valid_from)], now))
            written += n
            if n:
                symbols.add(f.symbol)
    finally:
        await client.close()
    print(f"{STEP_LABEL}: {len(fetches)} fetch(es), {client.request_count} request(s), {written} bar(s) over {len(symbols)} symbol(s), {len(errors)} error(s)")
    for e in errors[:20]:
        print("   ", e)
    await record_step_fields(STEP_LABEL, {"fetches": len(fetches), "requests": client.request_count, "retries": client.log.retries, "bars": written,
                                          "symbols": len(symbols), "errors": errors[:50]})
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
