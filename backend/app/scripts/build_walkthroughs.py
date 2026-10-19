"""Ivy's walkthrough for every active stock, rebuilt from stored data (services/walkthrough). Nightly step "Ivy walkthroughs".

    python -m app.scripts.build_walkthroughs                          # dry run: build every stock, print coverage, write nothing
    python -m app.scripts.build_walkthroughs --write                  # store payloads; stories for stocks whose story facts changed
    python -m app.scripts.build_walkthroughs --symbols=MU,JPM --write
    python -m app.scripts.build_walkthroughs --no-story               # rule-built steps only, no model calls
    python -m app.scripts.build_walkthroughs --report=out.json        # per-stock step statuses and reasons (Part 0 coverage)

Steps 2 (growth) and 5 (P/E) are built in full whatever GROWTH_ENABLED and PE_ENABLED say; the API applies the flags when it
serves a walkthrough (routers/walkthrough.gate), so a flag takes effect without a rebuild. A 10-K whose accession is already
stored is never read again. Model calls (story sentences, step 7's risk sentences, Compare's pair sentences) run only for a stock
whose story facts changed, each bounded by STORY_SECONDS, and stop for the night at NIGHTLY_STORY_CAP_USD (the rest wait for the
next run). The featured stock for the home page is chosen at the end by FEATURED_RULE.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import walkthrough as W
from app.services.redact import redact

STEP_LABEL = "Ivy walkthroughs"
SEC_SECONDS = 120                      # one SEC read (a 10-K's instance, its risk factors, the company facts) at most
FEATURED_KEY = "ivy_featured"


async def sources_for(edgar, sym: str, sector: str | None, stored: dict, today: date) -> dict:
    """The 10-K readings (segments, risk factors) and margins, reusing a stored reading of the same 10-K."""
    from app.scripts.compute_pe import company_facts_merged
    from app.services.edgar_client import PREDECESSOR_CIKS
    from app.services import margins as M, risk_factors as R, segments as S
    out = dict(stored or {})
    cik = await edgar.get_cik(sym)
    ciks = [c for c in [cik] + PREDECESSOR_CIKS.get(sym, []) if c]
    if not ciks:
        return {**out, "error": "no CIK"}
    _, k = await asyncio.wait_for(S.latest_annual_for(edgar, list(dict.fromkeys(ciks))), SEC_SECONDS)
    acc = k["accession"] if k else None
    if (out.get("segments") or {}).get("accession") != acc or (out.get("segments") or {}).get("version") != S.SEGMENTS_VERSION:
        seg = await asyncio.wait_for(S.read_segments(edgar, list(dict.fromkeys(ciks)), sector), SEC_SECONDS)
        out["segments"] = {**_jsonable(seg), "version": S.SEGMENTS_VERSION}
    if (out.get("risks") or {}).get("accession") != acc or (out.get("risks") or {}).get("version") != R.RISK_FACTORS_VERSION:
        rk = await asyncio.wait_for(R.read_risk_factors(edgar, list(dict.fromkeys(ciks))), SEC_SECONDS)
        out["risks"] = {**_jsonable(rk), "version": R.RISK_FACTORS_VERSION}
    periodic = latest_periodic(await edgar.get_submissions(cik)) if cik else None
    m = out.get("margins") or {}
    if cik and (m.get("periodic") != periodic or m.get("version") != M.MARGINS_VERSION or not m.get("periodic")):
        facts = await asyncio.wait_for(company_facts_merged(edgar, cik, sym), SEC_SECONDS)
        out["margins"] = {**_jsonable(M.margins(facts, sector, today)), "version": M.MARGINS_VERSION, "periodic": periodic}
    return out


def latest_periodic(submissions: dict) -> str | None:
    """Pure: the accession of the newest 10-Q or 10-K: the company facts change only when one is filed, so margins are recomputed
    only then (a night without one reads no company facts)."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    return next((a for f, a in zip(r.get("form") or [], r.get("accessionNumber") or []) if f in ("10-Q", "10-K", "10-KT")), None)


def _jsonable(d: dict) -> dict:
    return json.loads(json.dumps(d, default=str))


def _dates(d: dict | None, *keys: str) -> dict | None:
    """A stored reading with its ISO dates read back as dates."""
    if not d:
        return d
    out = dict(d)
    for k in keys:
        if isinstance(out.get(k), str):
            try:
                out[k] = date.fromisoformat(out[k][:10])
            except ValueError:
                pass
    return out


async def build_one(db, u: dict, sym: str, src: dict) -> dict:
    """Pure over the stored data and readings: {payload, steps_shown, story_facts}."""
    from app.services.briefing import short_name
    from app.services.fact_holds import holds_for
    from app.services.fomc_calendar import decision_days
    from app.services import walkthrough_data as D
    from app.thresholds import MARKET_DAY_MIN_SPY_PCT
    today = u["today"]
    t = u["tickers"][sym]
    name = short_name(re.sub(r"\s*\([^)]*\)\s*$", "", t["name"] or ""), sym) or sym     # "Clorox Company (The)", "Kimco Realty Corporation (HC)"
    sector = t["sector"]
    merger = u["mergers"].get(sym)
    held = set(await holds_for(db, sym))
    seg = _dates(src.get("segments"), "start", "end", "filed")
    risks = _dates(src.get("risks"), "filed")
    m = _dates(src.get("margins"), "now_start", "now_end", "then_end", "filed_on")
    actions = u["actions"].get(sym, [])
    s1 = W.step_business(name, u["profiles"].get(sym), seg, merger)
    growth_rows = u["growth"].get(sym)
    s2 = W.step_growth(name, growth_rows, sector, True)
    s3 = W.step_margins(name, m, actions)
    rdays = await D.report_days(db, t["id"])
    stock = u["closes"].get(sym, [])
    moves = D.biggest_moves(stock, u["spy"], rdays, MARKET_DAY_MIN_SPY_PCT)
    s4 = W.step_stock(name, sector, stock, u["spy"], u["sectors"].get(sector), moves, MARKET_DAY_MIN_SPY_PCT, today)
    snap = u["pe"].get(sym)
    if snap and "pe" in held:
        snap = None
    series = await D.pe_series(db, sym, u["splits"].get(sym, []), actions, today) if snap and snap["status"] == "ok" else []
    s5 = W.step_valuation(name, sector, snap, series, u["pe_sector"].get(sector), True)
    ne = u["next"].get(sym) if "report_date" not in held else None
    timing = None
    implied = None
    if ne and ne.date:
        timing = (await db.execute(text("SELECT report_timing FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date = :d LIMIT 1"),
                                   {"t": t["id"], "d": ne.date})).scalar()
        implied = None if "implied_move" in held else await D.implied_move(db, sym, ne.date, today)
    typical = await D.typical_move(db, t["id"], sym, held)
    fed = next(iter(decision_days(today, today + timedelta(days=400))), None)
    s6 = W.step_upcoming(name, ne, timing, implied, typical, fed)
    s7 = W.step_risks(name, risks, merger)
    steps = [s1, s2, s3, s4, s5, s6, s7]
    ttm = W.ttm_growth([r for r in growth_rows or [] if r["metric"] == "revenue"])
    stock_1y = D.change([(d, v) for d, v in stock], D.YEAR_SESSIONS) if s4["status"] != "absent" else None
    row = W.compare_row(name, sym, steps, seg, ttm[2] if ttm else None, m, stock_1y[0] if stock_1y else None,
                        float(snap["pe"]) if snap and snap["status"] == "ok" and snap.get("pe") is not None else None,
                        ne.date if ne and ne.date else None, bool(ne and ne.confirmation == "confirmed"))
    as_of = max([d for d, _ in u["spy"][-1:]] or [today])
    payload = {"version": W.WALKTHROUGH_VERSION, "symbol": sym, "name": name, "sector": sector, "industry": t["industry"], "minutes": W.MINUTES,
               "as_of": as_of.isoformat(), "steps": steps, "compare": row, "market_cap": t["market_cap"]}
    story_facts = {"name": name, "sector": sector, "description": (s1["sentences"][0] if s1["status"] != "absent" and u["profiles"].get(sym) else None),
                   "steps": {s["key"]: {"numbers": s["numbers"], "sentences": s["sentences"]} for s in (s1, s2, s3) if s["status"] != "absent"},
                   "risks": [{"n": r["n"], "heading": r["heading"], "body": r["body"]} for r in (risks or {}).get("risks", [])] if s7["status"] != "absent" else [],
                   "risk_filed": (risks or {}).get("filed").isoformat() if s7["status"] != "absent" and risks and risks.get("filed") else None}
    return {"payload": json.loads(json.dumps(payload, default=str)), "steps_shown": W.steps_shown(steps), "story_facts": story_facts, "as_of": as_of}


async def run(argv: list[str]) -> int:
    from app.services.edgar_client import EdgarClient
    from app.services.walkthrough_data import load_universe
    write = "--write" in argv
    story = "--no-story" not in argv
    only = [s.strip().upper() for a in argv if a.startswith("--symbols=") for s in a.split("=", 1)[1].split(",") if s.strip()]
    report = next((a.split("=", 1)[1] for a in argv if a.startswith("--report=")), None)
    today = date.today()
    async with ScriptSessionLocal() as db:
        u = await load_universe(db, today)
        stored = {r.symbol: dict(r._mapping) for r in (await db.execute(text(
            "SELECT symbol, sources, story, story_fingerprint, facts_fingerprint FROM ivy_walkthroughs"))).all()}
    symbols = [s for s in (only or list(u["tickers"])) if s in u["tickers"]]
    print(f"{STEP_LABEL}: {len(symbols)} stock(s) ({'write' if write else 'dry run'}{', stories' if story and write else ''}); closes through "
          f"{u['spy'][-1][0] if u['spy'] else None}", flush=True)
    edgar = EdgarClient()
    built: dict[str, dict] = {}
    rows: list[dict] = []
    sec_failed = 0
    try:
        for i, sym in enumerate(symbols, 1):
            prior = stored.get(sym) or {}
            try:
                src = await sources_for(edgar, sym, u["tickers"][sym]["sector"], prior.get("sources") or {}, today)
            except Exception as exc:
                sec_failed += 1
                print(f"  {sym}: SEC read failed, stored readings kept: {redact(exc)[:120]}", flush=True)
                src = prior.get("sources") or {}
            async with ScriptSessionLocal() as db:
                b = await build_one(db, u, sym, src)
            built[sym] = {**b, "sources": src, "prior": prior}
            st = {s["key"]: s["status"] for s in b["payload"]["steps"]}
            rows.append({"symbol": sym, "sector": u["tickers"][sym]["sector"], "steps": st,
                         "reasons": {s["key"]: s["absent"] for s in b["payload"]["steps"] if s["status"] == "absent"},
                         "segment_reason": (src.get("segments") or {}).get("reason"), "risk_reason": (src.get("risks") or {}).get("reason"),
                         "margin_measure": (src.get("margins") or {}).get("measure"), "margin_reason": (src.get("margins") or {}).get("reason")})
            if i % 50 == 0:
                print(f"  {i}/{len(symbols)} built", flush=True)
    finally:
        await edgar.close()

    from app.services import walkthrough_story as WS
    spent = 0.0
    if story and write:
        spent = await WS.run_stories(built, today)
    else:
        WS.reuse_stories(built)
    if write:
        async with ScriptSessionLocal() as db:
            for sym, b in built.items():
                payload = b["payload"]
                await db.execute(text("""
                    INSERT INTO ivy_walkthroughs (symbol, version, as_of, facts_fingerprint, story_fingerprint, payload, sources, story, steps_shown, built_at)
                    VALUES (:s, :v, :a, :f, :sf, CAST(:p AS jsonb), CAST(:src AS jsonb), CAST(:st AS jsonb), :n, now())
                    ON CONFLICT (symbol) DO UPDATE SET version = EXCLUDED.version, as_of = EXCLUDED.as_of, facts_fingerprint = EXCLUDED.facts_fingerprint,
                        story_fingerprint = EXCLUDED.story_fingerprint, payload = EXCLUDED.payload, sources = EXCLUDED.sources, story = EXCLUDED.story,
                        steps_shown = EXCLUDED.steps_shown, built_at = now()"""),
                    {"s": sym, "v": W.WALKTHROUGH_VERSION, "a": b["as_of"], "f": W.fingerprint(payload), "sf": b.get("story_fingerprint"),
                     "p": json.dumps(payload, default=str), "src": json.dumps(b["sources"], default=str), "st": json.dumps(b.get("story") or {}, default=str),
                     "n": b["steps_shown"]})
            if not only:
                # a ticker that left the index or stopped trading keeps no walkthrough
                await db.execute(text("DELETE FROM ivy_walkthroughs WHERE symbol NOT IN (SELECT symbol FROM tickers WHERE is_active)"))
                from app.services.walkthrough_compare import featured
                prev = (await db.execute(text("SELECT value FROM system_metadata WHERE key = :k"), {"k": FEATURED_KEY})).scalar()
                pick = featured(built, u, today, (json.loads(prev) or {}).get("history", []) if prev else [])
                await db.execute(text("""INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""), {"k": FEATURED_KEY, "v": json.dumps(pick, default=str)})
                print(f"  featured: {pick.get('symbol')} ({pick.get('why')})", flush=True)
            await db.commit()
    counts = {k: {"ok": 0, "partial": 0, "absent": 0} for k in W.KEYS.values()}
    for r in rows:
        for k, v in r["steps"].items():
            counts[k][v] += 1
    for k, c in counts.items():
        print(f"  step {k:<10} ok {c['ok']:>3}  partial {c['partial']:>3}  absent {c['absent']:>3}", flush=True)
    print(f"  SEC reads failed: {sec_failed}; story spend ${spent:.2f}", flush=True)
    if report:
        with open(report, "w") as fh:
            json.dump({"run_at": datetime.now(timezone.utc).isoformat(), "today": today.isoformat(), "counts": counts, "stocks": rows}, fh, default=str, indent=1)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
