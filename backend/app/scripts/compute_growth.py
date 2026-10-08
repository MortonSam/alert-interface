"""Quarterly revenue and GAAP diluted EPS growth against the same quarter a year earlier (services/growth), for the last four
reported quarters. Two readers must agree for each figure: XBRL as first filed, and the quarter's own earnings release (Item 2.02
8-K) or, failing that, the later filing's restated comparative. Disagreements are logged to growth_disagreements; with --write the
agreed figures go to growth_figures. Not in the nightly: computed locally until GROWTH_ENABLED is approved.

Usage: python -m app.scripts.compute_growth --symbols=MU,MSFT [--write]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.compute_pe import company_facts_merged
from app.scripts.seed_release_eps import exhibit_candidates
from app.services import growth as G
from app.services import valuation as V
from app.services.edgar_client import PREDECESSOR_CIKS, EdgarClient
from app.services.redact import redact

RELEASE_AFTER_DAYS = (10, 75)     # a quarter's earnings release is filed this many days after the quarter ends


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
            if r and (rev is None or (r["how"] == "revenue sentence" and rev["how"] != "revenue sentence")):
                rev = r
        if eps is not None or rev is not None:
            return {"eps": eps, "revenue": rev, "filed": filed, "accession": key}
    return {"eps": None, "revenue": None, "filed": None, "accession": None}


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "")
    symbols = [s.strip().upper() for s in only.split(",") if s.strip()]
    async with ScriptSessionLocal() as s:
        if not symbols:
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
    edgar = EdgarClient()
    tags_by_sector: dict[str, dict[str, int]] = {}
    rows_out: list[dict] = []
    disagreements: list[tuple] = []
    for sym in symbols:
        try:
            cik = await edgar.get_cik(sym)
            if not cik:
                print(f"{sym}: no CIK"); continue
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
        async with ScriptSessionLocal() as s:
            for r in rows_out:
                if r["value"] is None or r["year_ago_value"] is None:
                    continue
                await s.execute(text("""INSERT INTO growth_figures (symbol, metric, period_end, year_ago_end, value, year_ago_value, growth_pct, phrase, held_reason, readers, tag, version, computed_at)
                    VALUES (:symbol, :metric, :period_end, :year_ago_end, :value, :year_ago_value, :growth_pct, :phrase, :held_reason, :readers, :tag, :version, now())
                    ON CONFLICT ON CONSTRAINT uq_growth_symbol_metric_period DO UPDATE SET year_ago_end = EXCLUDED.year_ago_end, value = EXCLUDED.value,
                    year_ago_value = EXCLUDED.year_ago_value, growth_pct = EXCLUDED.growth_pct, phrase = EXCLUDED.phrase, held_reason = EXCLUDED.held_reason,
                    readers = EXCLUDED.readers, tag = EXCLUDED.tag, version = EXCLUDED.version, computed_at = now()"""), {k: v for k, v in r.items() if k != "release"})
            for d in disagreements:
                await s.execute(text("INSERT INTO growth_disagreements (symbol, metric, period_end, detail) VALUES (:a, :b, :c, :d)"), {"a": d[0], "b": d[1], "c": d[2], "d": d[3]})
            await s.commit()
        print("written to the local database")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
