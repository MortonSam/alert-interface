"""One-off repair: a symbol holding two current security records for the same Intrinio security (a moved first-price date read as a
new record, before build_security_records matched current rows by security id). Keeps the row the most price bars reference,
moves the duplicate's bars onto it, deletes the duplicate, and sets the kept row's start to the duplicate's (Intrinio's current
first_stock_price). Dry run unless --write.

Usage: python -m app.scripts.repair_duplicate_record BKR [--write]
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__); return 2
    sym = args[0].upper()
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT sr.id, sr.intrinio_security_id, sr.valid_from, sr.created_at, count(b.date) AS bars, min(b.date), max(b.date)
            FROM security_records sr LEFT JOIN price_bars_shadow b ON b.security_record_id = sr.id
            WHERE sr.symbol = :s AND sr.role = 'current' GROUP BY sr.id ORDER BY count(b.date) DESC, sr.created_at"""), {"s": sym})).all()
        if len(rows) < 2:
            print(f"{sym}: {len(rows)} current record(s); nothing to repair"); return 0
        if len({r[1] for r in rows}) != 1:
            print(f"{sym}: current records name different Intrinio securities {sorted({r[1] for r in rows})}; not a duplicate, not repaired"); return 1
        keep, dups = rows[0], rows[1:]
        newest_start = max(dups, key=lambda r: r[3])[2]            # the duplicate's start is Intrinio's current first_stock_price
        print(f"{sym}: keep record {keep[0]} (start {keep[2]}, {keep[4]} bars {keep[5]}..{keep[6]}); its start becomes {newest_start}")
        for d in dups:
            print(f"  delete duplicate {d[0]} (start {d[2]}, created {d[3]:%Y-%m-%d}); move its {d[4]} bars ({d[5]}..{d[6]}) onto the kept record")
        if not write:
            print("  dry run, nothing written"); return 0
        for d in dups:
            await s.execute(text("UPDATE price_bars_shadow SET security_record_id = :k WHERE security_record_id = :d"), {"k": keep[0], "d": d[0]})
            await s.execute(text("DELETE FROM security_records WHERE id = :d"), {"d": d[0]})
        await s.execute(text("UPDATE security_records SET valid_from = :v, updated_at = now() WHERE id = :k"), {"v": newest_start, "k": keep[0]})
        await s.commit()
        print("  repaired")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
