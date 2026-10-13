"""Relabel one stored release_eps row as basic: a figure stored as diluted before 2026-10-13 from a release that states no diluted
EPS anywhere (AEP 2026-07-30, "GAAP earnings ... or $1.31 per share"). Dry run by default; --write updates the one row.

Refuses unless: the eps_basis column exists (migration e1f2a3b4c5d6 is live); the row exists and is stored as diluted; the
release (the stored accession and exhibit, re-read from EDGAR) states no diluted EPS (valuation.states_diluted_eps); and the
pattern reader still reads the stored figure from it. The update moves the figure from diluted_eps_gaap to basic_eps_gaap and sets
eps_basis = 'basic' in one transaction, and commits only when exactly one row changed.

    python -m app.scripts.relabel_release_eps_basis --symbol=AEP --date=2026-07-30            # dry run
    python -m app.scripts.relabel_release_eps_basis --symbol=AEP --date=2026-07-30 --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import EdgarClient
from app.services.valuation import parse_release_basic_eps, parse_release_eps, states_diluted_eps

UPDATE = """UPDATE release_eps SET basic_eps_gaap = diluted_eps_gaap, diluted_eps_gaap = NULL, eps_basis = 'basic'
            WHERE symbol = :s AND report_date = :d AND eps_basis = 'diluted'"""


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


def refusal(row: dict | None, exhibit_text: str | None, report_date: date) -> str | None:
    """Pure: why the row may not be relabelled, or None when it may."""
    if row is None:
        return "no stored row"
    if row["eps_basis"] != "diluted":
        return f"already stored as {row['eps_basis']}"
    if exhibit_text is None:
        return "the stored exhibit could not be read"
    if states_diluted_eps(exhibit_text):
        return "the release states diluted EPS: the stored figure stays diluted"
    hit = parse_release_eps(exhibit_text, report_date) or parse_release_basic_eps(exhibit_text, report_date)
    if hit is None or round(hit["eps"], 2) != round(float(row["diluted_eps_gaap"]), 2):
        return f"the release no longer reads as the stored figure ({hit['eps'] if hit else 'nothing read'} against {float(row['diluted_eps_gaap']):+.2f})"
    return None


async def run(argv: list[str]) -> int:
    sym, d = (_arg(argv, "symbol") or "").upper(), _arg(argv, "date")
    if not sym or not d:
        print("usage: --symbol=SYM --date=YYYY-MM-DD [--write]")
        return 2
    report_date, write = date.fromisoformat(d), "--write" in argv
    async with ScriptSessionLocal() as s:
        has_column = (await s.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'release_eps' AND column_name = 'eps_basis'"))).first()
        if not has_column:
            print("refused: release_eps.eps_basis does not exist (migration e1f2a3b4c5d6 is not live)")
            return 1
        row = (await s.execute(text("""SELECT symbol, report_date, diluted_eps_gaap, basic_eps_gaap, eps_basis, accession, exhibit, how
            FROM release_eps WHERE symbol = :s AND report_date = :d"""), {"s": sym, "d": report_date})).mappings().first()
    exhibit_text = None
    if row is not None:
        edgar = EdgarClient()
        try:
            cik = await asyncio.wait_for(edgar.get_cik(sym), 60)
            recs = [r for r in await asyncio.wait_for(edgar.get_all_8k_records(cik), 60) if r["accession"] == row["accession"]]
            prim = (recs[0].get("primary_document") or "") if recs else ""
            texts = await asyncio.wait_for(edgar.filing_texts(cik, row["accession"], prim), 120)
            exhibit_text = next((t for n, t in texts if n == row["exhibit"]), None)
        finally:
            await edgar.close()
    print(f"{sym} {report_date}: stored {dict(row) if row else None}")
    why = refusal(dict(row) if row else None, exhibit_text, report_date)
    if why:
        print(f"refused: {why}")
        return 1
    print(f"would set eps_basis 'basic', basic_eps_gaap {float(row['diluted_eps_gaap']):+.2f}, diluted_eps_gaap NULL" + ("" if write else "; dry run, nothing written"))
    if not write:
        return 0
    async with ScriptSessionLocal() as s:
        n = (await s.execute(text(UPDATE), {"s": sym, "d": report_date})).rowcount
        if n != 1:
            await s.rollback()
            print(f"refused: the update matched {n} rows; rolled back")
            return 1
        await s.commit()
        after = (await s.execute(text("SELECT eps_basis, basic_eps_gaap, diluted_eps_gaap FROM release_eps WHERE symbol = :s AND report_date = :d"),
                                 {"s": sym, "d": report_date})).one()
    print(f"written: {sym} {report_date} now {tuple(after)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
