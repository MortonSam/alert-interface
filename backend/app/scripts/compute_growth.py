"""Quarterly revenue and GAAP diluted EPS growth against the same quarter a year earlier (services/growth), for the last four
reported quarters. Two readers must agree for each figure: XBRL as first filed, and the quarter's own earnings release (Item 2.02
8-K) or, failing that, the later filing's restated comparative. Disagreements are logged to growth_disagreements (a recomputed
symbol's earlier ones are replaced, so the table holds the current readings); with --write the agreed figures go to growth_figures.
The nightly runs --due --write (Block 2, 2026-10-20); what visitors see stays behind GROWTH_ENABLED.

--due (2026-10-21: the step hit its 3600-second limit with nothing written, every night): a ticker is due only when EDGAR's filing
index shows a 10-Q, 10-K, 20-F or 40-F, or an 8-K with Item 2.02 (a results release), accepted after its last growth run, or when it
has never run. Each run is recorded per ticker (system_metadata growth_run:{SYM}) whatever it found, each ticker's figures are
written as soon as it is done, and the run starts no new ticker after RUN_BUDGET_S, so it ends inside ten minutes; a ticker it
didn't reach is still due the next night (the newest filings first, never-run tickers after them).

Usage: python -m app.scripts.compute_growth --symbols=MU,MSFT [--write]
       python -m app.scripts.compute_growth --due --write      # the nightly: every ticker that reported since its figures were computed
"""
from __future__ import annotations

import asyncio
import sys
import json
import time
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.compute_pe import company_facts_merged
from app.scripts.seed_release_eps import exhibit_candidates
from app.services import growth as G
from app.services import valuation as V
from app.services.edgar_client import PREDECESSOR_CIKS, EdgarClient
from app.services.redact import redact
from app.services.system_metadata_service import set_value

RELEASE_AFTER_DAYS = (10, 75)     # a quarter's earnings release is filed this many days after the quarter ends
STEP_LABEL = "Growth (XBRL and 8-K releases)"
RUN_BUDGET_S = 8 * 60             # --due: no new ticker starts after this
RUN_HARD_S = 9 * 60               # --due: a ticker still running now stops (it stays due), so the step ends inside ten minutes
WORKERS = 6                       # --due: tickers read at once; every SEC request still waits its turn (edgar_client's pacing)
RUN_KEY = "growth_run:{sym}"      # system_metadata: {"at": <when the ticker's last growth run finished>}
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "40-F", "20-F/A", "40-F/A"}

# the release reading that outranks another, when two exhibits both read: the consolidated statement's row, a company-level sentence,
# then any other table (Block 2: a supplement's first "net revenue" row may be a segment's, JPM's Consumer & Community Banking)
def _rank(rev: dict) -> int:
    how = rev.get("how") or ""
    return 0 if "consolidated statement" in how or "consolidating statement" in how else (1 if how == "revenue sentence" else 2)


def newest_filing(submissions: dict) -> datetime | None:
    """Pure: when the newest filing growth reads was accepted (a periodic report, or an 8-K with Item 2.02), from EDGAR's index."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    best = None
    for form, items, acc in zip(r.get("form") or [], r.get("items") or [], r.get("acceptanceDateTime") or []):
        if form in PERIODIC_FORMS or (form in ("8-K", "8-K/A") and "2.02" in (items or "")):
            try:
                at = datetime.fromisoformat(acc.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            best = at if best is None or at > best else best
    return best


def due_order(last_runs: dict[str, datetime | None], newest: dict[str, datetime | None]) -> list[str]:
    """Pure: the due tickers, newest filing first, then the never-run ones by symbol. A ticker is due with a growth filing accepted
    after its last run, or with no run at all."""
    fresh = [(n, sym) for sym, n in newest.items() if n is not None and last_runs.get(sym) is not None and n > last_runs[sym]]
    never = sorted(sym for sym, at in last_runs.items() if at is None)
    return [sym for _, sym in sorted(fresh, reverse=True)] + never


async def last_runs(s) -> dict[str, datetime | None]:
    """Every active ticker's last growth run: its recorded run, else when its figures or disagreements were last written."""
    rows = (await s.execute(text("""SELECT t.symbol, greatest(g.at, d.at, (m.value::json->>'at')::timestamptz) FROM tickers t
        LEFT JOIN (SELECT symbol, max(computed_at) AS at FROM growth_figures GROUP BY symbol) g ON g.symbol = t.symbol
        LEFT JOIN (SELECT symbol, max(logged_at) AS at FROM growth_disagreements GROUP BY symbol) d ON d.symbol = t.symbol
        LEFT JOIN system_metadata m ON m.key = 'growth_run:' || t.symbol
        WHERE t.is_active ORDER BY t.symbol"""))).all()
    return {sym: (at.replace(tzinfo=timezone.utc) if at is not None and at.tzinfo is None else at) for sym, at in rows}


async def due_symbols(s, edgar: EdgarClient) -> list[str]:
    """--due: the tickers with a growth filing since their last run (one filing-index read each), or never run."""
    runs = await last_runs(s)
    newest: dict[str, datetime | None] = {}
    for sym, at in runs.items():
        if at is None:
            continue
        try:
            cik = await edgar.get_cik(sym)
            newest[sym] = newest_filing(await edgar.get_submissions(cik)) if cik else None
        except Exception as exc:
            print(f"  {sym}: filing index unread, not due tonight: {redact(exc)[:100]}")
    return due_order(runs, newest)


async def _release(edgar: EdgarClient, cik: str, records: list[dict], end: date, cache: dict) -> dict:
    """The quarter's earnings release readings: {eps, revenue, filed, accession} (each None when unread)."""
    recs = sorted((r for r in records if "2.02" in (r.get("items") or "")
                   and RELEASE_AFTER_DAYS[0] <= (date.fromisoformat(r["filing_date"]) - end).days <= RELEASE_AFTER_DAYS[1]),
                  key=lambda r: r["filing_date"])
    for rec in recs:
        key = rec["accession"]
        if key not in cache:
            texts = await edgar.filing_texts(rec.get("_cik", cik), rec["accession"], rec.get("primary_document") or rec.get("primaryDocument", ""))
            cache[key] = exhibit_candidates(texts)
        filed = date.fromisoformat(rec["filing_date"])
        eps = rev = None
        for _, body in cache[key]:
            hit = V.parse_release_eps(body, filed)
            if hit and eps is None and (hit.get("period_end") is None or abs((hit["period_end"] - end).days) <= 10):
                eps = hit["eps"]
            r = G.parse_release_revenue(body)
            # the company-level revenue sentence in any exhibit outranks a table row (a supplement's first "net revenue" row may be
            # a segment's: JPM's Consumer & Community Banking)
            if r and (rev is None or _rank(r) < _rank(rev)):
                rev = r
        if eps is not None or rev is not None:
            return {"eps": eps, "revenue": rev, "filed": filed, "accession": key}
    return {"eps": None, "revenue": None, "filed": None, "accession": None}


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "")
    symbols = [s.strip().upper() for s in only.split(",") if s.strip()]
    due = "--due" in argv
    t0 = time.time()
    edgar = EdgarClient()
    async with ScriptSessionLocal() as s:
        if due:
            symbols = await due_symbols(s, edgar)
            print(f"{STEP_LABEL}: {len(symbols)} ticker(s) due ({time.time() - t0:.0f}s to find them)", flush=True)
            if not symbols:
                return 0
        elif not symbols:
            symbols = list((await s.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
        sectors = dict((await s.execute(text("SELECT symbol, sector FROM tickers WHERE symbol = ANY(:s)"), {"s": symbols})).all())
        splits: dict[str, list] = {}
        for r in (await s.execute(text("""SELECT t.symbol, e.event_date, e.metadata->>'split_ratio' FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = ANY(:s) AND e.event_type = 'split' ORDER BY e.event_date"""), {"s": symbols})).all():
            splits.setdefault(r[0], []).append((r[1], V.split_ratio(r[2])))
        actions: dict[str, list[dict]] = {}
        for r in (await s.execute(text("""SELECT t.symbol, e.event_date, COALESCE(e.metadata->>'corporate_action', 'spin_off'), e.metadata->>'counterparty' FROM events e
            JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = ANY(:s) AND (e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata ? 'corporate_action'))"""),
                                     {"s": symbols})).all():
            actions.setdefault(r[0], []).append({"kind": r[2], "date": r[1], "name": r[3]})
        # release EPS already stored by seed_release_eps, where its two readers (the pattern parser and the model) agreed: for a fiscal
        # fourth quarter it replaces the year total less three quarters, which drifts by cents as share counts change
        stored_release = {r[0]: (float(r[1]), r[2]) for r in (await s.execute(text(
            "SELECT accession, diluted_eps_gaap, report_date FROM release_eps WHERE symbol = ANY(:s) AND eps_basis = 'diluted'"), {"s": symbols})).all()}
    tags_by_sector: dict[str, dict[str, int]] = {}

    async def process(sym: str) -> tuple[list[dict], list[tuple]] | None:
        """One ticker's rows and disagreements, or None when it failed (it stays due)."""
        rows_out: list[dict] = []
        disagreements: list[tuple] = []
        try:
            cik = await edgar.get_cik(sym)
            if not cik:
                print(f"{sym}: no CIK")
                return rows_out, disagreements
            facts = await company_facts_merged(edgar, cik, sym)
            us = facts.get("facts", {}).get("us-gaap", {})
            # a company that moved to a new CIK (XOM to ExxonMobil Holdings in 2026): its revenue facts and 8-K releases before the
            # move are under the predecessor CIK (edgar_client.PREDECESSOR_CIKS); company_facts_merged merges EPS only
            others = [c for c in PREDECESSOR_CIKS.get(sym, []) if c.zfill(10) != cik.zfill(10)]
            for other in others:
                try:
                    ous = (await edgar.get_company_facts(other)).get("facts", {}).get("us-gaap", {})
                except Exception as exc:
                    print(f"  {sym}: predecessor CIK {other} facts unread: {redact(exc)[:100]}")
                    continue
                for tag in G.revenue_tags(sectors.get(sym)):
                    extra = ous.get(tag, {}).get("units", {}).get("USD", [])
                    if extra:
                        us.setdefault(tag, {}).setdefault("units", {}).setdefault("USD", [])
                        us[tag]["units"]["USD"] = us[tag]["units"]["USD"] + extra
            eps_q = G.quarter_readings(us.get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", []), True, splits.get(sym))
            recent = G.latest_quarters(eps_q)
            needed = recent + [y for y in (G.year_ago(e, eps_q) for e in recent) if y]
            by_tag = G.revenue_by_tag(us, sectors.get(sym))
            # per comparison: the revenue tag carrying both quarters; EPS has one tag
            pairs: dict[tuple[str, date], tuple[str | None, dict, date | None]] = {}
            for end in recent:
                pairs[("revenue", end)] = G.tag_for_pair(by_tag, end)
                pairs[("eps", end)] = ("EarningsPerShareDiluted", eps_q, G.year_ago(end, eps_q) if end in eps_q else None)
                tag_used = pairs[("revenue", end)][0]
                if tag_used:
                    tags_by_sector.setdefault(sectors.get(sym) or "?", {}).setdefault(tag_used, 0)
                    tags_by_sector[sectors.get(sym) or "?"][tag_used] += 1
            needed = sorted({e for (_, end), (_, _, ya) in pairs.items() for e in (end, ya) if e})
            records = list(await edgar.get_all_8k_records(cik))
            for other in others:
                try:
                    records += [{**r, "_cik": other} for r in await edgar.get_all_8k_records(other)]
                except Exception as exc:
                    print(f"  {sym}: predecessor CIK {other} 8-Ks unread: {redact(exc)[:100]}")
            cache: dict = {}
            releases = {end: await _release(edgar, cik, records, end, cache) for end in needed}
            agreed: dict[tuple[str, date], tuple[float, str]] = {}

            def confirm_one(metric: str, qs: dict, end: date):
                if end not in qs:
                    return None
                rel = releases[end]
                if metric == "eps" and qs[end]["derived"] and rel["accession"] in stored_release:
                    eps, report_date = stored_release[rel["accession"]]
                    return (round(eps / V.split_factor(report_date, splits.get(sym))[0], 4),
                            "the stored release EPS (its two readers agreed), for a fiscal fourth quarter")
                rv = rel[metric]
                if metric == "eps" and rv is not None and rel["filed"]:
                    rv = round(rv / V.split_factor(rel["filed"], splits.get(sym))[0], 4)
                val, readers, why = G.confirm(metric, qs[end], rv)
                if val is None:
                    disagreements.append((sym, metric, end, why))
                    return None
                return (val, readers)
            for metric in ("revenue", "eps"):
                for end in recent:
                    tag, qs, prior_end = pairs[(metric, end)]
                    cur = confirm_one(metric, qs, end)
                    pri = confirm_one(metric, qs, prior_end) if prior_end else None
                    held = G.hold_for_actions(actions.get(sym, []), qs[prior_end]["start"] if prior_end and prior_end in qs else end, end)
                    if cur and pri:
                        pct, phrase = G.growth_words(metric, cur[0], pri[0])
                    else:
                        pct, phrase = None, None
                    rows_out.append({"symbol": sym, "metric": metric, "period_end": end, "year_ago_end": prior_end,
                                     "value": cur[0] if cur else None, "year_ago_value": pri[0] if pri else None,
                                     "growth_pct": None if held else pct, "phrase": None if held else phrase, "held_reason": held,
                                     "readers": f"{cur[1] if cur else 'unconfirmed'} / {pri[1] if pri else 'unconfirmed'}",
                                     "tag": tag, "version": G.GROWTH_VERSION,
                                     "release": releases[end].get("accession")})
        except Exception as exc:
            print(f"{sym}: failed: {redact(exc)[:160]}")
            return None                                         # not recorded as run: due again next time
        return rows_out, disagreements

    rows_out: list[dict] = []
    disagreements: list[tuple] = []
    done_syms: list[str] = []
    queue = list(symbols)

    async def worker() -> None:
        while queue:
            if due and time.time() - t0 > RUN_BUDGET_S:
                return
            sym = queue.pop(0)
            try:
                got = await (asyncio.wait_for(process(sym), max(5.0, RUN_HARD_S - (time.time() - t0))) if due else process(sym))
            except asyncio.TimeoutError:
                print(f"{sym}: stopped at the run's {RUN_HARD_S}s limit, due again next run", flush=True)
                continue
            if got is None:
                continue
            if write:
                await write_symbol(sym, *got)
            rows_out.extend(got[0])
            disagreements.extend(got[1])
            done_syms.append(sym)
    await asyncio.gather(*(worker() for _ in range(WORKERS if due else 1)))
    if due and len(done_syms) < len(symbols):
        print(f"budget of {RUN_BUDGET_S}s reached: {len(symbols) - len(done_syms)} ticker(s) left due for the next run", flush=True)
    for r in rows_out:
        fmt = (lambda v: f"${v / 1e9:,.3f}B" if v is not None and abs(v) >= 1e9 else (f"${v / 1e6:,.1f}M" if v is not None else "—")) if r["metric"] == "revenue" \
            else (lambda v: f"${v:,.2f}" if v is not None else "—")
        print(f"{r['symbol']:5s} {r['metric']:7s} {r['period_end']}  {fmt(r['value']):>11s} vs {fmt(r['year_ago_value']):>11s} ({r['year_ago_end']})  "
              f"{r['held_reason'] or r['phrase'] or 'not shown'}  [{r['readers']}] {r['tag'] if r['metric'] == 'revenue' else ''} release {r['release']}")
    print(f"\n{len(disagreements)} disagreement(s), logged and never shown:")
    for d in disagreements:
        print(f"  {d[0]} {d[1]} {d[2]}: {d[3]}")
    print("\nrevenue tags by sector: " + "; ".join(f"{sec}: " + ", ".join(f"{t} ({n})" for t, n in tags.items()) for sec, tags in sorted(tags_by_sector.items())))
    if write:
        print(f"written to the local database: {len(done_syms)} ticker(s) in {time.time() - t0:.0f}s")
    await edgar.close()
    return 0


async def write_symbol(sym: str, rows: list[dict], disagreements: list[tuple]) -> None:
    """One ticker's agreed figures and current disagreements, and the record of its run, committed as soon as it is done."""
    async with ScriptSessionLocal() as s:
        for r in rows:
            if r["value"] is None or r["year_ago_value"] is None:
                continue
            await s.execute(text("""INSERT INTO growth_figures (symbol, metric, period_end, year_ago_end, value, year_ago_value, growth_pct, phrase, held_reason, readers, tag, version, computed_at)
                VALUES (:symbol, :metric, :period_end, :year_ago_end, :value, :year_ago_value, :growth_pct, :phrase, :held_reason, :readers, :tag, :version, now())
                ON CONFLICT ON CONSTRAINT uq_growth_symbol_metric_period DO UPDATE SET year_ago_end = EXCLUDED.year_ago_end, value = EXCLUDED.value,
                year_ago_value = EXCLUDED.year_ago_value, growth_pct = EXCLUDED.growth_pct, phrase = EXCLUDED.phrase, held_reason = EXCLUDED.held_reason,
                readers = EXCLUDED.readers, tag = EXCLUDED.tag, version = EXCLUDED.version, computed_at = now()"""), {k: v for k, v in r.items() if k != "release"})
        await s.execute(text("DELETE FROM growth_disagreements WHERE symbol = :s"), {"s": sym})   # the current readings only
        for d in disagreements:
            await s.execute(text("INSERT INTO growth_disagreements (symbol, metric, period_end, detail) VALUES (:a, :b, :c, :d)"), {"a": d[0], "b": d[1], "c": d[2], "d": d[3]})
        await set_value(s, RUN_KEY.format(sym=sym), json.dumps({"at": datetime.now(timezone.utc).isoformat()}))
        await s.commit()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
