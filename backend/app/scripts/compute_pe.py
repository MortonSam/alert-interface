"""Nightly trailing P/E for every active ticker (services/valuation): the latest stored close over the four latest reported
quarters' GAAP diluted EPS, from eps_quarters (XBRL, refreshed when a newer report may have landed) plus release_eps when the
latest report is newer than XBRL. Stores a pe_snapshots row per ticker per price date with its window, the four quarters and
their receipts, a "not meaningful" status when trailing EPS is zero or negative ("lost money over the last four quarters"),
or "missing" with the reason; and a pe_sector_snapshots row per sector, shown only at 90% coverage. Dry run by default.

    python -m app.scripts.compute_pe                 # dry run: computes everything, prints coverage by sector, stores nothing
    python -m app.scripts.compute_pe --write         # the nightly step
    python -m app.scripts.compute_pe MU NVDA --write
    python -m app.scripts.compute_pe --reread --write   # re-parse every ticker's quarters from the cached company facts
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import valuation as V
from app.services.edgar_client import PREDECESSOR_CIKS, EdgarClient
from app.services.redact import redact
from app.services.write_failures import WriteFailures
from app.services.write_failures import WriteFailures
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Trailing P/E"
WRITES = WriteFailures(STEP_LABEL)
WRITES = WriteFailures(STEP_LABEL)


def _eps_series(facts: dict) -> list[dict]:
    return facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", [])


async def company_facts_merged(edgar: EdgarClient, cik: str, symbol: str) -> dict:
    """Company facts for a CIK plus those of the ticker's predecessor CIKs named in edgar_client.PREDECESSOR_CIKS (PSKY's filings
    under Paramount Global's CIK). Never the CIK in an accession prefix: that is the submitter, often a filing agent, and Workiva
    Inc. files for its clients under its own CIK, so its calendar-quarter EPS (0.33 for 2026-03-31, 0.24 for 2026-06-30) once
    merged into COST, AMZN, AON and some fifty others, replacing Amazon's own quarter where the period ends matched."""
    facts = await edgar.get_company_facts(cik)
    series = list(_eps_series(facts))
    for other in PREDECESSOR_CIKS.get(symbol.upper(), []):
        if other.zfill(10) == cik.zfill(10):
            continue
        try:
            series.extend(_eps_series(await edgar.get_company_facts(other)))
        except Exception:
            continue
    if series:
        facts.setdefault("facts", {}).setdefault("us-gaap", {}).setdefault("EarningsPerShareDiluted", {}).setdefault("units", {})["USD/shares"] = series
    return facts


def _rows_to_quarters(rows) -> list[dict]:
    return [{"end": r[0], "start": r[1], "eps": float(r[2]), "filed": r[3], "form": r[4], "derived": bool(r[5]), "source": "xbrl"} for r in rows]


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    reread = "--reread" in argv            # re-parse every ticker's quarters from the (cached) company facts, e.g. after a parser change
    only = [a.upper() for a in argv if not a.startswith("--")]
    today = date.today()
    async with ScriptSessionLocal() as s:
        tickers = (await s.execute(text("SELECT symbol, sector FROM tickers WHERE is_active" + (" AND symbol = ANY(:o)" if only else "") + " ORDER BY symbol"), {"o": only})).all()
        symbols = [t[0] for t in tickers]
        closes = {r[0]: (r[1], float(r[2])) for r in (await s.execute(text(
            "SELECT DISTINCT ON (symbol) symbol, date, close FROM price_bars_shadow WHERE symbol = ANY(:s) ORDER BY symbol, date DESC"), {"s": symbols})).all()}
        latest_report = dict((await s.execute(text("""
            SELECT symbol, max(d) FROM (
                SELECT t.symbol, e.event_date AS d FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE t.symbol = ANY(:s) AND e.event_type = 'earnings' AND e.event_date <= :t AND (e.is_confirmed OR e.eps_actual IS NOT NULL)
                UNION ALL
                SELECT t.symbol, hr.event_date FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
                WHERE t.symbol = ANY(:s) AND hr.event_type = 'earnings' AND hr.event_date <= :t) x GROUP BY symbol"""), {"s": symbols, "t": today})).all())
        releases = {r[0]: {"report_date": r[1], "period_end": r[2], "eps": float(r[3]), "accession": r[4]} for r in
                    (await s.execute(text("SELECT DISTINCT ON (symbol) symbol, report_date, period_end, diluted_eps_gaap, accession FROM release_eps WHERE symbol = ANY(:s) ORDER BY symbol, report_date DESC"), {"s": symbols})).all()}
        # recorded corporate actions: spin-offs (events.spin_off), actions recorded by record_corporate_action (events.other with
        # metadata.corporate_action) and rename-merges (ticker_aliases)
        # recorded splits, [(effective date, new-for-old ratio, recorded at)]: quarters and closes are restated across them (valuation.split_factor)
        splits: dict[str, list[tuple]] = {}
        for r in (await s.execute(text("""SELECT t.symbol, e.event_date, e.metadata->>'split_ratio', e.created_at FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = ANY(:s) AND e.event_type = 'split' ORDER BY e.event_date"""), {"s": symbols})).all():
            splits.setdefault(r[0], []).append((r[1], V.split_ratio(r[2]), r[3]))
        actions: dict[str, list[dict]] = {}
        for r in (await s.execute(text("""SELECT t.symbol, e.event_date, COALESCE(e.metadata->>'corporate_action', 'spin_off'), e.metadata->>'counterparty' FROM events e
            JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = ANY(:s) AND (e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata ? 'corporate_action'))"""), {"s": symbols})).all():
            actions.setdefault(r[0], []).append({"kind": r[2], "date": r[1], "name": r[3]})
        for r in (await s.execute(text("SELECT symbol, old_symbol, renamed_on FROM ticker_aliases WHERE symbol = ANY(:s)"), {"s": symbols})).all():
            actions.setdefault(r[0], []).append({"kind": "rename_merge", "date": r[2], "name": r[1]})
        stored: dict[str, list[dict]] = {}
        fetched: dict[str, datetime] = {}
        for r in (await s.execute(text("SELECT symbol, period_end, period_start, eps, filed_on, form, derived, diluted_shares, fetched_at FROM eps_quarters WHERE symbol = ANY(:s) ORDER BY symbol, period_end"), {"s": symbols})).all():
            stored.setdefault(r[0], []).append({"end": r[1], "start": r[2], "eps": float(r[3]), "filed": r[4], "form": r[5], "derived": bool(r[6]), "source": "xbrl",
                                                "diluted_shares": float(r[7]) if r[7] is not None else None})
            fetched[r[0]] = max(fetched.get(r[0], r[8]), r[8])
    print(f"{STEP_LABEL}: {len(symbols)} active ticker(s) ({'write' if write else 'dry run'}); closes through {max((c[0] for c in closes.values()), default=None)}", flush=True)
    edgar = EdgarClient()
    refreshed = failed = 0
    snapshots: dict[str, dict] = {}
    try:
        for sym in symbols:
            quarters = stored.get(sym, [])
            lr = latest_report.get(sym)
            # a split recorded since the quarters were last read restates them: read again (stored rows carry the basis of their read)
            split_since = any(created and sym in fetched and created > fetched[sym] for _, _, created in splits.get(sym, []))
            if reread or split_since or V.needs_refresh(quarters, lr, today):
                try:
                    cik = await edgar.get_cik(sym)
                    quarters = V.eps_quarters(await company_facts_merged(edgar, cik, sym), [(d, ratio) for d, ratio, _ in splits.get(sym, [])]) if cik else []
                    refreshed += 1
                    if write:
                        async with ScriptSessionLocal() as s:
                            # a stored quarter the facts no longer yield (a merged filer's quarter, a restated period end) is removed, so the table is the facts
                            gone = (await s.execute(text("DELETE FROM eps_quarters WHERE symbol = :s AND NOT (period_end = ANY(:ends))"), {"s": sym, "ends": [q["end"] for q in quarters]})).rowcount
                            if gone:
                                print(f"  {sym}: removed {gone} stored quarter(s) the company facts do not yield", flush=True)
                            for q in quarters:
                                await s.execute(text("""INSERT INTO eps_quarters (symbol, period_end, period_start, eps, filed_on, form, derived, diluted_shares, fetched_at)
                                    VALUES (:s, :e, :st, :eps, :f, :form, :d, :sh, now()) ON CONFLICT (symbol, period_end) DO UPDATE SET period_start = EXCLUDED.period_start,
                                    eps = EXCLUDED.eps, filed_on = EXCLUDED.filed_on, form = EXCLUDED.form, derived = EXCLUDED.derived, diluted_shares = EXCLUDED.diluted_shares, fetched_at = now()"""),
                                    {"s": sym, "e": q["end"], "st": q["start"], "eps": q["eps"], "f": q["filed"], "form": q["form"][:12], "d": q["derived"], "sh": q.get("diluted_shares")})
                            await s.commit()
                except Exception as exc:
                    WRITES.note(sym, exc)                  # a database error while storing the quarters fails the step; an EDGAR failure does not
                    print(f"  {sym}: XBRL failed: {redact(exc)[:100]}", flush=True); failed += 1
                    quarters = stored.get(sym, [])
            rel = releases.get(sym)
            rel = rel if rel and lr and rel["report_date"] == lr else None
            close = closes.get(sym)
            snap = V.snapshot_with_actions(close[1] if close else None, quarters, lr, rel, today, actions.get(sym, []))
            snap["as_of_date"] = close[0] if close else today
            snap["price"] = close[1] if close else None
            if snap["status"] == "ok":
                async with ScriptSessionLocal() as s:
                    bars = [(d, float(c)) for d, c in (await s.execute(text("SELECT date, close FROM price_bars_shadow WHERE symbol = :s AND date >= :d ORDER BY date"),
                                                                        {"s": sym, "d": today - timedelta(days=366 * V.RANGE_YEARS)})).all()]
                bars = V.rebase_closes(bars, [(d, ratio) for d, ratio, _ in splits.get(sym, [])])
                snap["history"] = V.pe_history_clean(bars, quarters, snap["pe"], [a["date"] for a in actions.get(sym, [])])
            snapshots[sym] = snap
    finally:
        await edgar.close()
    # sector medians
    by_sector: dict[str, list[tuple[str, float | None]]] = {}
    active: dict[str, int] = {}
    for sym, sec in tickers:
        sec = sec or "unclassified"
        active[sec] = active.get(sec, 0) + 1
        sn = snapshots.get(sym)
        if sn:
            by_sector.setdefault(sec, []).append((sn["status"], sn["pe"]))
    sectors = {sec: V.sector_summary(by_sector.get(sec, []), n) for sec, n in active.items()}
    if only:
        sectors = {}      # a subset run cannot judge sector coverage; the nightly runs over every active ticker
    as_of = max((sn["as_of_date"] for sn in snapshots.values()), default=today)
    if write:
        async with ScriptSessionLocal() as s:
            for sym, sn in snapshots.items():
                if sn["price"] is None:
                    continue
                h = sn.get("history") or {}
                await s.execute(text("""
                    INSERT INTO pe_snapshots (symbol, as_of_date, price, status, reason, trailing_eps, pe, window_start, window_end, window_source, latest_report, quarters,
                                              hist_median, hist_share_above, hist_sessions, hist_excluded, hist_first, hist_last, computed_at, computation_version)
                    VALUES (:s, :d, :p, :st, :r, :te, :pe, :ws, :we, :src, :lr, CAST(:q AS jsonb), :hm, :hs, :hn, :hx, :hf, :hl, now(), :v)
                    ON CONFLICT (symbol, as_of_date) DO UPDATE SET price = EXCLUDED.price, status = EXCLUDED.status, reason = EXCLUDED.reason, trailing_eps = EXCLUDED.trailing_eps,
                        pe = EXCLUDED.pe, window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end, window_source = EXCLUDED.window_source, latest_report = EXCLUDED.latest_report,
                        quarters = EXCLUDED.quarters, hist_median = EXCLUDED.hist_median, hist_share_above = EXCLUDED.hist_share_above, hist_sessions = EXCLUDED.hist_sessions,
                        hist_excluded = EXCLUDED.hist_excluded, hist_first = EXCLUDED.hist_first, hist_last = EXCLUDED.hist_last, computed_at = now(),
                        computation_version = EXCLUDED.computation_version"""),
                    {"v": V.PE_COMPUTATION_VERSION, "s": sym, "d": sn["as_of_date"], "p": sn["price"], "st": sn["status"], "r": sn["reason"], "te": sn["trailing_eps"], "pe": sn["pe"], "ws": sn["window_start"], "we": sn["window_end"],
                     "src": sn["window_source"], "lr": sn["latest_report"], "q": json.dumps(sn["quarters"]) if sn["quarters"] else None, "hm": h.get("median"), "hs": h.get("share_above"),
                     "hn": h.get("sessions"), "hx": h.get("excluded"), "hf": h.get("first"), "hl": h.get("last")})
            for sec, summ in sectors.items():
                await s.execute(text("""INSERT INTO pe_sector_snapshots (sector, as_of_date, median_pe, with_pe, fresh, active, shown, reason, computed_at)
                    VALUES (:sec, :d, :m, :w, :f, :a, :sh, :r, now()) ON CONFLICT (sector, as_of_date) DO UPDATE SET median_pe = EXCLUDED.median_pe, with_pe = EXCLUDED.with_pe,
                    fresh = EXCLUDED.fresh, active = EXCLUDED.active, shown = EXCLUDED.shown, reason = EXCLUDED.reason, computed_at = now()"""),
                    {"sec": sec, "d": as_of, "m": summ["median_pe"], "w": summ["with_pe"], "f": summ["fresh"], "a": summ["active"], "sh": summ["shown"], "r": summ["reason"]})
            await s.commit()
    counts = {k: sum(1 for sn in snapshots.values() if sn["status"] == k) for k in ("ok", "not_meaningful", "not_meaningful_yet", "missing")}
    print(f"\n  coverage: {counts['ok']} with a P/E, {counts['not_meaningful']} not meaningful, {counts['not_meaningful_yet']} not meaningful yet (corporate action in the window), "
          f"{counts['missing']} missing; {refreshed} XBRL read(s), {failed} failed")
    for sym, sn in sorted(snapshots.items()):
        if sn["status"] == "not_meaningful_yet":
            print(f"    {sym}: {sn['reason']}")
    print(f"  {'sector':<28} {'P/E':>5} {'n/m':>5} {'miss':>5} {'active':>7}  median  shown")
    missing_reasons: dict[str, int] = {}
    for sec in sorted(sectors):
        rows = [snapshots[sym] for sym, s2 in tickers if (s2 or "unclassified") == sec and sym in snapshots]
        ok = sum(1 for r in rows if r["status"] == "ok"); nm = sum(1 for r in rows if r["status"] in ("not_meaningful", "not_meaningful_yet")); miss = active[sec] - ok - nm
        summ = sectors[sec]
        print(f"  {sec:<28} {ok:>5} {nm:>5} {miss:>5} {active[sec]:>7}  {summ['median_pe'] if summ['median_pe'] is not None else '—':>6}  {'yes' if summ['shown'] else 'no: ' + (summ['reason'] or '')}")
    for sn in snapshots.values():
        if sn["status"] == "missing":
            key = (sn["reason"] or "").split(" (")[0][:60]
            missing_reasons[key] = missing_reasons.get(key, 0) + 1
    if missing_reasons:
        print("  missing, by reason: " + "; ".join(f"{k}: {n}" for k, n in sorted(missing_reasons.items(), key=lambda x: -x[1])[:6]))
    if write:
        await record_step_fields(STEP_LABEL, {**counts, "refreshed": refreshed, "failed": failed, "sectors_shown": sum(1 for s2 in sectors.values() if s2["shown"]), "error": None})
    return await WRITES.finish(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
