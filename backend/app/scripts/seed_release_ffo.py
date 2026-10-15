"""FFO per share for every REIT (services/ffo): each earnings report in the last LOOKBACK_DAYS, read from the Item 2.02 8-K's exhibit by
the pattern parser and the model (both must agree to the cent), cross-checked against XBRL, and written to ffo_quarters with --write.
Dry run by default. Prints one line per report and the coverage across all REITs at the end; --report=PATH writes that summary.

    python -m app.scripts.seed_release_ffo                       # every REIT, dry run
    python -m app.scripts.seed_release_ffo O PLD --write
    python -m app.scripts.seed_release_ffo --no-model            # the pattern parser alone (nothing could store)
    python -m app.scripts.seed_release_ffo --due --write         # the nightly: reports with no shown or held row yet
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.seed_release_eps import MATCH_DAYS, exhibit_candidates, filing_period_end
from app.services import ffo as F
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.valuation import release_period_end

LOOKBACK_DAYS = 460          # five quarters back, so the newest four each have a year-ago quarter
CALL_TIMEOUT = 90            # seconds for any one EDGAR or model call


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    use_model = "--no-model" not in argv
    report_path = next((a.split("=", 1)[1] for a in argv if a.startswith("--report=")), None)
    only = {a.upper() for a in argv if not a.startswith("--")}
    since = date.today() - timedelta(days=LOOKBACK_DAYS)
    async with ScriptSessionLocal() as s:
        reits = [(r.symbol, r.industry) for r in (await s.execute(text("SELECT symbol, sector, industry FROM tickers WHERE is_active ORDER BY symbol"))).all()
                 if F.is_reit(r.sector, r.industry) and (not only or r.symbol in only)]
        done: set = set()
        if "--due" in argv:                       # the nightly: only reports with no shown or held row yet
            done = {(r.symbol, r.report_date) for r in (await s.execute(text("SELECT symbol, report_date FROM ffo_quarters WHERE state IN ('ok', 'held')"))).all()}
        reports = {}
        for sym, _ in reits:
            reports[sym] = sorted({r[0] for r in (await s.execute(text("""SELECT DISTINCT hr.event_date FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
                WHERE t.symbol = :s AND hr.event_type = 'earnings' AND hr.event_date BETWEEN :a AND CURRENT_DATE"""), {"s": sym, "a": since})).all()
                                   if (sym, r[0]) not in done})
    model_client = None
    if use_model:
        from app.config import settings
        if settings.anthropic_api_key:
            from app.services.anthropic_client import AnthropicClient
            model_client = AnthropicClient()
    edgar = EdgarClient()
    rows, cost = [], 0.0
    try:
        for sym, industry in reits:
            try:
                cik = await asyncio.wait_for(edgar.get_cik(sym), CALL_TIMEOUT)
                eightks = [r for r in await asyncio.wait_for(edgar.get_all_8k_records(cik), CALL_TIMEOUT) if "2.02" in (r.get("items") or "")] if cik else []
                facts = await asyncio.wait_for(edgar.get_company_facts(cik), CALL_TIMEOUT) if cik else {}
            except Exception as exc:
                print(f"{sym}: EDGAR failed: {redact(exc)[:100]}"); continue
            xbrl = F.xbrl_ffo_quarters(facts)
            for rd in reports[sym]:
                row = {"symbol": sym, "report_date": rd, "period_end": None, "ffo": None, "state": "unread", "reason": None, "quote": None,
                       "xbrl": None, "gap": None, "accession": None, "exhibit": None}
                recs = [r for r in eightks if abs((date.fromisoformat(r["filing_date"]) - rd).days) <= MATCH_DAYS]
                if not recs:
                    row["reason"] = f"no Item 2.02 8-K within {MATCH_DAYS} days"; rows.append(row); print(f"  {sym} {rd}: {row['reason']}"); continue
                hit = ex = rec = texts = None
                for rec in recs:
                    texts = await asyncio.wait_for(edgar.filing_texts(cik, rec["accession"], rec.get("primary_document") or rec.get("primaryDocument", "")), CALL_TIMEOUT)
                    for cand in exhibit_candidates(texts):
                        hit = F.parse_release_ffo(cand[1])
                        if hit:
                            ex = cand; break
                    if hit:
                        break
                cands = exhibit_candidates(texts or [])
                exhibit = ex or (cands[0] if cands else None)
                if exhibit is None:
                    row["reason"] = "the 8-K has no readable exhibit"; rows.append(row); print(f"  {sym} {rd}: {row['reason']}"); continue
                model = None
                if model_client is not None:
                    try:
                        model = await asyncio.wait_for(F.model_read(model_client, exhibit[1], rd), CALL_TIMEOUT)
                        cost += model.get("cost_usd") or 0
                    except Exception as exc:
                        print(f"  {sym} {rd}: model failed: {redact(exc)[:80]}")
                figure, note = F.decide_ffo(hit, model, exhibit[1])
                pe = release_period_end(exhibit[1], rd) or filing_period_end(texts or [], rd)
                row.update(period_end=pe, accession=rec["accession"] if rec else None, exhibit=exhibit[0], quote=(model or {}).get("quote") or (hit or {}).get("evidence"))
                if figure is None:
                    row["reason"] = note
                elif pe is None:
                    row["reason"] = f"{note}; the release states no quarter end"
                else:
                    state, gap, why = F.cross_check(figure, xbrl.get(pe))
                    row.update(ffo=figure, state=state, gap=gap, xbrl=(xbrl.get(pe) or {}).get("ffo_per_share"), reason=why)
                rows.append(row)
                print(f"  {sym} {rd} (quarter {pe}): {row['state']}, {('%.2f' % row['ffo']) if row['ffo'] is not None else '-'}; {row['reason']}")
    finally:
        await edgar.close()
    if write:
        async with ScriptSessionLocal() as s:
            for r in rows:
                if r["period_end"] is None:
                    continue
                await s.execute(text("""INSERT INTO ffo_quarters (symbol, period_end, report_date, ffo_per_share, state, reason, quote, xbrl_ffo_per_share, xbrl_gap_pct,
                        accession, exhibit, computation_version, read_at)
                    VALUES (:symbol, :period_end, :report_date, :ffo, :state, :reason, :quote, :xbrl, :gap, :accession, :exhibit, :v, :at)
                    ON CONFLICT (symbol, period_end) DO UPDATE SET report_date = EXCLUDED.report_date, ffo_per_share = EXCLUDED.ffo_per_share,
                        state = EXCLUDED.state, reason = EXCLUDED.reason, quote = EXCLUDED.quote, xbrl_ffo_per_share = EXCLUDED.xbrl_ffo_per_share,
                        xbrl_gap_pct = EXCLUDED.xbrl_gap_pct, accession = EXCLUDED.accession, exhibit = EXCLUDED.exhibit,
                        computation_version = EXCLUDED.computation_version, read_at = EXCLUDED.read_at"""),
                                {**r, "v": F.FFO_COMPUTATION_VERSION, "at": datetime.now(timezone.utc)})
            await s.commit()
    summary = coverage(rows, [s for s, _ in reits], cost)
    print(summary)
    if report_path:
        with open(report_path, "w") as fh:
            fh.write(summary + "\n\n" + "\n".join(f"| {r['symbol']} | {r['report_date']} | {r['period_end'] or ''} | {r['state']} | "
                                                  f"{'' if r['ffo'] is None else '%.2f' % r['ffo']} | {'' if r['xbrl'] is None else '%.2f' % r['xbrl']} | "
                                                  f"{'' if r['gap'] is None else '%.1f%%' % r['gap']} | {(r['reason'] or '').replace('|', '/')[:200]} |" for r in rows))
    print("written" if write else "dry run: nothing written (add --write)")
    return 0


def coverage(rows: list[dict], reits: list[str], cost: float) -> str:
    """Pure: the coverage summary across every REIT: reports read, shown, held and unread, and the REITs with a shown latest quarter."""
    by = {s: [r for r in rows if r["symbol"] == s] for s in reits}
    shown = sum(1 for r in rows if r["state"] == "ok")
    held = sum(1 for r in rows if r["state"] == "held")
    latest_ok = [s for s, rs in by.items() if rs and max(rs, key=lambda r: r["report_date"])["state"] == "ok"]
    none = [s for s, rs in by.items() if not any(r["state"] == "ok" for r in rs)]
    return (f"FFO coverage: {len(reits)} REITs, {len(rows)} reports; {shown} shown, {held} held (XBRL gap over {F.FFO_GAP_PCT:.0f}%), "
            f"{len(rows) - shown - held} unread; latest quarter shown for {len(latest_ok)} of {len(reits)}; no quarter shown for "
            f"{len(none)} ({', '.join(none) or 'none'}); model cost ${cost:.2f}\n\n| Symbol | Report | Quarter | State | FFO/share | XBRL | Gap | Reason |\n|---|---|---|---|---|---|---|---|")


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
