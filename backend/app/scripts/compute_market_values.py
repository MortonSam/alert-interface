"""Market values for every active stock (services/market_value): the shares on the cover of the company's latest 10-Q or 10-K,
each class times its own latest licensed close, one figure per company. Nightly step "Market values", after the price bars.
A cover is fetched and read only when its accession is not the one on file; the close is the newest in price_bars_shadow. A
company on the hold-out list, or one whose cover cannot be read tonight, is written with no value and the reason. No model call.

    python -m app.scripts.compute_market_values                  # dry run: prints what it would write
    python -m app.scripts.compute_market_values --write [--symbols=GOOG,NVDA]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import market_value as MV
from app.services.edgar_client import EdgarClient
from app.services.redact import redact

STEP_LABEL = "Market values"
UNREADABLE = "no shares outstanding could be read from the cover"

_UPSERT = text("""INSERT INTO market_values (symbol, company, value, held_reason, shares, classes, shares_as_of, close_date, accession, form, filed, version, computed_at)
    VALUES (:symbol, :company, :value, :held_reason, :shares, CAST(:classes AS jsonb), :shares_as_of, :close_date, :accession, :form, :filed, :version, now())
    ON CONFLICT (symbol) DO UPDATE SET company = EXCLUDED.company, value = EXCLUDED.value, held_reason = EXCLUDED.held_reason, shares = EXCLUDED.shares,
        classes = EXCLUDED.classes, shares_as_of = EXCLUDED.shares_as_of, close_date = EXCLUDED.close_date, accession = EXCLUDED.accession, form = EXCLUDED.form,
        filed = EXCLUDED.filed, version = EXCLUDED.version, computed_at = now()""")


def stored_cover(row) -> dict | None:
    """Pure: the cover read on an earlier night, from its market_values row (None when the row holds no classes)."""
    if not row or not row["classes"] or not row["shares_as_of"]:
        return None
    classes = [(c["member"], float(c["shares"])) for c in row["classes"]]
    return {"as_of": row["shares_as_of"], "classes": classes, "total": sum(v for _, v in classes)}


async def cover_for(edgar: EdgarClient, key: str, row) -> tuple[dict | None, dict | None, str | None]:
    """(cover, filing, why not): the company's latest 10-Q or 10-K cover, read from the row on file while its accession is unchanged."""
    cik = await edgar.get_cik(key.replace(".", "-"))
    if cik is None:
        return None, None, "no CIK for the symbol"
    f = MV.latest_cover_filing(await edgar.get_submissions(cik))
    if f is None:
        return None, None, MV.NO_COVER
    if row and row["accession"] == f["accession"] and row["version"] == MV.MARKET_VALUE_VERSION and stored_cover(row):
        return stored_cover(row), f, None
    cover = MV.cover_shares(await edgar.fetch_filing_html(cik, f["accession"], f["document"]))
    return cover, f, None if cover else UNREADABLE


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = [s.strip().upper() for a in argv if a.startswith("--symbols=") for s in a.split("=", 1)[1].split(",") if s.strip()]
    async with ScriptSessionLocal() as db:
        symbols = list((await db.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
        closes = {r.symbol: (r.date, float(r.close)) for r in (await db.execute(text("""SELECT DISTINCT ON (symbol) symbol, date, close FROM price_bars_shadow
            WHERE symbol = ANY(:s) AND close IS NOT NULL ORDER BY symbol, date DESC"""), {"s": symbols})).all()}
        closes = MV.fresh_closes(closes)
        splits = {r.symbol: r.day for r in (await db.execute(text("""SELECT symbol, max(date) AS day FROM price_bars_shadow
            WHERE symbol = ANY(:s) AND split_ratio <> 1 GROUP BY symbol"""), {"s": symbols})).all()}
        on_file = {r["symbol"]: dict(r) for r in (await db.execute(text("SELECT * FROM market_values"))).mappings().all()}
    active = set(symbols)
    companies: dict[str, list[str]] = {}
    for sym in symbols:
        if not only or sym in only or MV.company_of(sym) in {MV.company_of(o) for o in only}:
            companies.setdefault(MV.company_of(sym), []).append(sym)
    edgar = EdgarClient()
    rows, failed = [], []
    try:
        for key, syms in companies.items():
            try:
                cover, filing, why = await cover_for(edgar, key, on_file.get(key) or on_file.get(syms[0]))
            except Exception as exc:                      # one company's failed read is reported and keeps what it has on file
                failed.append(key)
                print(f"  {key}: not read tonight ({type(exc).__name__}: {redact(exc)}); the row on file stands", flush=True)
                continue
            listed = [s for s in MV.company_symbols(key) if s in active]
            split_after = max([splits[s] for s in listed if s in splits], default=None)
            v = MV.company_value(key, cover, closes, split_after)
            if cover is None and why:
                v["held_reason"] = MV.held_reason(key, None) or why
            for sym in syms:
                rows.append({"symbol": sym, "company": key, "value": round(v["value"], 2) if v["value"] is not None else None, "held_reason": v["held_reason"],
                             "shares": v["shares"], "classes": json.dumps(v["classes"], default=str), "shares_as_of": v["shares_as_of"], "close_date": v["close_date"],
                             "accession": filing["accession"] if filing else None, "form": filing["form"] if filing else None,
                             "filed": date.fromisoformat(filing["filed"]) if filing else None, "version": MV.MARKET_VALUE_VERSION})
    finally:
        await edgar.close()
    valued = [r for r in rows if r["value"] is not None]
    held = [r for r in rows if r["value"] is None]
    if write and rows:
        async with ScriptSessionLocal() as db:
            await db.execute(_UPSERT, rows)
            await db.commit()
    for r in held:
        print(f"  {r['symbol']}: no figure ({r['held_reason']})", flush=True)
    out = {"stocks": len(rows), "with_a_figure": len(valued), "no_figure": len(held), "not_read": len(failed), "written": bool(write)}
    if write:
        from app.services.step_outcomes import record_step_fields
        await record_step_fields(STEP_LABEL, out)
    print(f"{STEP_LABEL}: {len(valued)} of {len(rows)} stock(s) with a figure, {len(held)} with none, {len(failed)} compan{'y' if len(failed) == 1 else 'ies'} not read"
          f" ({'written' if write else 'dry run'})", flush=True)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
