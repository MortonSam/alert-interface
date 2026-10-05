"""Rename a ticker in place: same id, same history, an alias for the old symbol. Dry run by default; --write applies.

The records build does this on its own when Intrinio returns a record under a new ticker; this script is for a rename
known before the build sees it, or to repeat one on another database.

    python -m app.scripts.rename_ticker EQR VMRK
    python -m app.scripts.rename_ticker EQR VMRK --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date

from app.database import ScriptSessionLocal
from app.services.ticker_rename import rename_symbol, symbol_tables


async def run(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    old, new = args[0].upper(), args[1].upper()
    write = "--write" in argv
    async with ScriptSessionLocal() as s:
        tables = await symbol_tables(s)
        print(f"Rename {old} -> {new} ({'write' if write else 'dry run'}): tables carrying a symbol: {', '.join(tables)}")
        if not write:
            return 0
        changed = await rename_symbol(s, old, new, date.today(), f"renamed by rename_ticker on {date.today().isoformat()}")
        await s.commit()
    print("  changed:", changed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
