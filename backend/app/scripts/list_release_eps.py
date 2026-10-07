"""Read-only: every release_eps row the nightly has stored, newest report first, with the figure, how it was read, its XBRL check and the
evidence line, so the stored figures can be audited before the P/E is ever enabled. Writes nothing, requests nothing.

    python -m app.scripts.list_release_eps                 # every row
    python -m app.scripts.list_release_eps --symbols=CRL,SMCI
    python -m app.scripts.list_release_eps --flagged       # rows whose XBRL figure disagrees
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

COLUMNS = "symbol, report_date, period_end, diluted_eps_gaap, how, accession, xbrl_eps, xbrl_form, difference, flagged, xbrl_note, evidence"


def xbrl_status(r) -> str:
    """Pure: one word on the row's XBRL check."""
    if r["flagged"]:
        return f"FLAGGED vs XBRL {float(r['xbrl_eps']):+.2f}"
    if r["xbrl_eps"] is not None:
        return f"matches XBRL {float(r['xbrl_eps']):+.2f} ({r['xbrl_form']})"
    if r["xbrl_note"]:
        return "not comparable (XBRL derives the quarter)"
    return "awaiting XBRL"


def format_rows(rows) -> list[str]:
    """Pure: one line per row: ticker, report date, quarter end, figure, how, accession, XBRL status, then the evidence indented."""
    out = []
    for r in rows:
        out.append(f"{r['symbol']:<6} {r['report_date']}  quarter ended {r['period_end'] or '?'}  GAAP diluted EPS {float(r['diluted_eps_gaap']):+.2f}  ({r['how']}; 8-K {r['accession']})  {xbrl_status(r)}")
        out.append(f"       evidence: {' '.join(str(r['evidence']).split())[:220]}")
    return out


async def run(argv: list[str]) -> int:
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    where = ["flagged"] if "--flagged" in argv else []
    params: dict = {}
    if only:
        where.append("symbol = ANY(:s)"); params["s"] = [x.strip().upper() for x in only.split(",") if x.strip()]
    sql = f"SELECT {COLUMNS} FROM release_eps" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY report_date DESC, symbol"
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text(sql), params)).mappings().all()
    print(f"release_eps: {len(rows)} stored figure(s)" + (f" for {only}" if only else "") + (", flagged only" if "--flagged" in argv else ""))
    for line in format_rows(rows):
        print(line)
    flagged = sum(1 for r in rows if r["flagged"])
    print(f"  {len(rows)} rows, {sum(1 for r in rows if r['xbrl_eps'] is not None)} checked against XBRL, {flagged} flagged, {sum(1 for r in rows if r['xbrl_note'])} not comparable, "
          f"{sum(1 for r in rows if r['xbrl_eps'] is None and not r['xbrl_note'])} awaiting XBRL")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
