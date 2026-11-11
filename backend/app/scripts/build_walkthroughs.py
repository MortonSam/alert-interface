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
FILING_GROWTH_VERSION = 1             # step 2's fallback: the filing's own growth where the release reads differently (2026-11-10)
SEC_SECONDS = 120                      # one SEC read (a 10-K's instance, its risk factors, the company facts) at most
FEATURED_KEY = "ivy_featured"


async def sources_for(edgar, sym: str, sector: str | None, stored: dict, today: date, industry: str | None = None) -> dict:
    """The 10-K readings (segments, risk factors) and margins, reusing a stored reading of the same 10-K."""
    from app.scripts.compute_pe import company_facts_merged
    from app.services.edgar_client import PREDECESSOR_CIKS
    from app.services import fiscal_periods as F, margins as M, risk_factors as R, segments as S
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
    p = out.get("periods") or {}
    fgs = out.get("filing_growth") or {}
    if cik and (m.get("periodic") != periodic or m.get("version") != M.MARGINS_VERSION or not m.get("periodic")
                or fgs.get("periodic") != periodic or fgs.get("version") != FILING_GROWTH_VERSION
                or p.get("periodic") != periodic or p.get("version") != F.FISCAL_PERIODS_VERSION):
        facts = await asyncio.wait_for(company_facts_merged(edgar, cik, sym), SEC_SECONDS)
        out["margins"] = {**_jsonable(M.margins(facts, sector, today, industry)), "version": M.MARGINS_VERSION, "periodic": periodic}
        from app.services.growth import filing_growth
        fg = filing_growth((facts.get("facts") or {}).get("us-gaap") or {}, sector, today)
        out["filing_growth"] = {**_jsonable(fg or {}), "ok": bool(fg), "version": FILING_GROWTH_VERSION, "periodic": periodic}
        out["periods"] = {"map": F.period_map(facts), "version": F.FISCAL_PERIODS_VERSION, "periodic": periodic}
    return out


def latest_periodic(submissions: dict) -> str | None:
    """Pure: the accession of the newest 10-Q or 10-K: the company facts change only when one is filed, so margins are recomputed
    only then (a night without one reads no company facts)."""
    r = (submissions.get("filings") or {}).get("recent") or {}
    return next((a for f, a in zip(r.get("form") or [], r.get("accessionNumber") or []) if f in ("10-Q", "10-K", "10-KT")), None)


def _iso_date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


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
    from app.services.fiscal_periods import quarter_label
    from app.services import walkthrough_data as D
    from app.thresholds import MARKET_DAY_MIN_SPY_PCT
    today = u["today"]
    t = u["tickers"][sym]
    name = short_name(re.sub(r"\s*\([^)]*\)\s*$", "", t["name"] or ""), sym) or sym     # "Clorox Company (The)", "Kimco Realty Corporation (HC)"
    sector = t["sector"]
    reit = W.is_reit(sector, t["industry"])
    noun = W.noun_for(t["industry"])
    merger = u["mergers"].get(sym)
    held = set(await holds_for(db, sym))
    periods = (src.get("periods") or {}).get("map") or {}
    seg = _dates(src.get("segments"), "start", "end", "filed")
    risks = _dates(src.get("risks"), "filed")
    m = _dates(src.get("margins"), "now_start", "now_end", "then_end", "filed_on")
    actions = u["actions"].get(sym, [])
    ffo = await D.ffo_figures(db, sym) if reit else None
    close = await D.last_close(db, sym)
    s1 = W.step_business(name, u["profiles"].get(sym), seg, merger, periods, noun, u["notes"].get(sym))
    growth_rows = u["growth"].get(sym)
    fg = _dates(src.get("filing_growth"), "period_end", "year_ago_end", "filed") if (src.get("filing_growth") or {}).get("ok") else None
    s2 = W.step_growth(name, growth_rows, sector, True, periods, reit, ffo, noun, filing=fg)
    s3 = W.step_margins(name, m, actions, periods, noun)
    rdays = await D.report_days(db, t["id"])
    stock = u["closes"].get(sym, [])
    moves = D.biggest_moves(stock, u["spy"], rdays, MARKET_DAY_MIN_SPY_PCT)
    s4 = W.step_stock(name, sector, stock, u["spy"], u["sectors"].get(sector), moves, MARKET_DAY_MIN_SPY_PCT, today, W.index_share(sym, u["tickers"]))
    snap = u["pe"].get(sym)
    if snap and "pe" in held:
        snap = None
    pe_behind = None
    if snap and snap["status"] == "missing" and (last_ok := u.get("pe_last_ok", {}).get(sym)) and W.last_pe_usable(last_ok, snap, today):
        pe_behind, snap = snap, last_ok           # the last P/E on file, labelled with its own date and quarter (W.pe_behind_line)
    if reit:
        s5 = W.step_valuation_reit(name, ffo, close, periods)
    else:
        series, left_out, year = [], {}, None
        if snap and snap["status"] == "ok":
            from app.services import valuation as V
            bars, quarters = await D.pe_inputs(db, sym, u["splits"].get(sym, []), today)
            act_dates = [a["date"] for a in actions]
            series = V.pe_series_clean(bars, quarters, act_dates) if quarters else []
            left_out = D.pe_left_out(bars, quarters, act_dates)
            year = D.pe_year(bars, quarters, snap, s4.get("year_pct"))
        s5 = W.step_valuation(name, sector, snap, series, u["pe_sector"].get(sector), True, periods, left_out, year)
        if pe_behind and s5["status"] != "absent":
            s5["sentences"].append(W.pe_behind_line(pe_behind.get("latest_report"), snap, periods))
            s5["status"], s5["behind"] = "partial", {"end": str(snap["window_end"]), "latest_report": str(pe_behind.get("latest_report"))}
            s5["gap"] = f"{W.gap_topic(5, noun)} (its newest quarter isn't in its filings' data yet)"
    ne = u["next"].get(sym) if "report_date" not in held else None
    timing = None
    implied = None
    if ne and ne.date:
        timing = (await db.execute(text("SELECT report_timing FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date = :d LIMIT 1"),
                                   {"t": t["id"], "d": ne.date})).scalar()
        implied = None if "implied_move" in held else await D.implied_move(db, sym, ne.date, today)
    typical = await D.typical_move(db, t["id"], sym, held)
    report_share = None                              # the report's own share of the move, as Ivy's Read states it, against the same typical move
    if ne and ne.date and getattr(ne, "confirmation", None) == "confirmed":
        from app.services.report_move import report_move_view
        v = await report_move_view(db, sym, ne.date, today, held, typical=(typical["pct"], typical["n"]) if typical else (None, 0))
        if v.get("rep") is not None:
            report_share = {"pct": v["rep"], "chain_date": v["chain_date"], "verdict": v.get("move_comparison")}
    s6 = W.step_upcoming(name, ne, timing, implied, typical, None, D.ordinary_move(stock, rdays) if typical else None, report_share)
    s7 = W.step_risks(name, risks, merger)
    steps = [s1, s2, s3, s4, s5, s6, s7]
    # one quarter across the steps (W.one_quarter): the latest quarter the company has filed, and each quarter step's own period end
    def _end(cell: dict | None, *keys: str) -> date | None:
        for k in keys:
            v = (cell or {}).get(k)
            v = next(iter(v.values()), None) if isinstance(v, dict) and "end" not in v else v
            if isinstance(v, dict) and v.get("end"):
                return date.fromisoformat(str(v["end"])[:10])
        return None
    pe_end = (snap or {}).get("window_end") if not reit and s5["status"] != "absent" else None
    reit_end = (((ffo or {}).get("ttm") or {}).get("end")) if reit and s5["status"] != "absent" else None
    quarter_ends = {2: _end(s2.get("cell"), "quarter", "ttm") if s2["status"] != "absent" else None,
                    3: _end(s3.get("cell"), "keeps_now") if s3["status"] != "absent" else None,
                    5: _iso_date(pe_end or reit_end)}
    # the latest quarter the company has REPORTED (Sam, 2026-11-10): filed before today and ended before its latest report on file,
    # never a quarter that has merely ended
    reported_on = (await db.execute(text("""SELECT max(e.event_date) FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s
        AND e.event_type = 'earnings' AND e.event_date <= :d AND (e.is_confirmed OR e.eps_actual IS NOT NULL)"""), {"s": sym, "d": today})).scalar()
    filed_latest = (await db.execute(text("SELECT max(period_end) FROM eps_quarters WHERE symbol = :s AND filed_on IS NOT NULL AND filed_on <= :d"),
                                     {"s": sym, "d": today})).scalar()
    latest_q = W.reported_quarter([filed_latest, *quarter_ends.values()], reported_on)
    quarter_check = {"latest": str(latest_q) if latest_q else None, "ends": {str(k): str(v) if v else None for k, v in quarter_ends.items()},
                     "replaced": W.one_quarter(steps, quarter_ends, latest_q, periods, name, noun, reit)}
    s2, s3, s5 = steps[1], steps[2], steps[4]
    fl = (ffo or {}).get("latest")
    ffo_cell = ({"value": W.signed(fl["growth_pct"]), "as_of": f"{quarter_label(periods, fl['end'])}, against a year earlier", "end": str(fl["end"])}
                if fl and fl.get("growth_pct") is not None else None)
    row = W.compare_row(name, sym, steps, reit=reit, noun=noun, ffo_growth=ffo_cell, dividend=await D.dividend_yield(db, sym, close))
    as_of = max([d for d, _ in u["spy"][-1:]] or [today])
    payload = {"version": W.WALKTHROUGH_VERSION, "symbol": sym, "name": name, "sector": sector, "industry": t["industry"], "reit": reit, "noun": noun, "minutes": W.MINUTES,
               "as_of": as_of.isoformat(), "steps": steps, "compare": row}
    story_facts = {"name": name, "sector": sector, "industry": t["industry"], "noun": noun,
                   "description": (s1["sentences"][0] if s1["status"] != "absent" and u["profiles"].get(sym) and not s1.get("from_note") else None),
                   "from_note": bool(s1.get("from_note")),
                   "business": ((risks or {}).get("business") or None) if s1["status"] != "absent" and not W.predates(merger, (risks or {}).get("filed")) else None,
                   "steps": {s["key"]: {"numbers": list(s["numbers"]), "sentences": list(s["sentences"]), "deeper": list(s["deeper"])} for s in (s1, s2, s3) if s["status"] != "absent"},
                   "risks": [{"n": r["n"], "heading": r["heading"], "body": r["body"]} for r in (risks or {}).get("risks", [])] if s7["status"] != "absent" else [],
                   "risk_filed": (risks or {}).get("filed").isoformat() if s7["status"] != "absent" and risks and risks.get("filed") else None}
    from app.services import walkthrough_quotes as Q
    latest_growth = max((r for r in growth_rows or [] if r["metric"] == "revenue" and not r.get("held_reason") and r.get("value") is not None),
                        key=lambda r: r["period_end"], default=None)
    want = Q.wanted(payload, latest_growth, m, periods)
    return {"payload": json.loads(json.dumps(payload, default=str)), "steps_shown": W.steps_shown(steps), "story_facts": story_facts, "as_of": as_of,
            "quote_want": json.loads(json.dumps(want, default=str)), "quarter_check": quarter_check}


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
    from app.services import walkthrough_story as WS
    edgar = EdgarClient()
    built: dict[str, dict] = {}
    rows: list[dict] = []
    sec_failed = 0
    quote_spend = 0.0
    try:
        for i, sym in enumerate(symbols, 1):
            prior = stored.get(sym) or {}
            try:
                src = await sources_for(edgar, sym, u["tickers"][sym]["sector"], prior.get("sources") or {}, today, u["tickers"][sym]["industry"])
            except Exception as exc:
                sec_failed += 1
                print(f"  {sym}: SEC read failed, stored readings kept: {redact(exc)[:120]}", flush=True)
                src = prior.get("sources") or {}
            async with ScriptSessionLocal() as db:
                b = await build_one(db, u, sym, src)
            from app.services import walkthrough_quotes as Q
            try:
                # the quotes' checks share the night's walkthrough budget with the stories (WS.NIGHTLY_STORY_CAP_USD)
                q = await Q.refresh(edgar, await edgar.get_cik(sym), b["quote_want"], src.get("quotes"), b["payload"]["name"],
                                    story and write and quote_spend < WS.NIGHTLY_STORY_CAP_USD)
                if q.get("cost_usd"):
                    quote_spend += q["cost_usd"]
                    print(f"  {sym}: quotes {sorted(q['quotes'])} kept, {len(q.get('dropped') or [])} dropped, ${q['cost_usd']:.3f}", flush=True)
            except Exception as exc:
                print(f"  {sym}: quotes failed, none shown: {redact(exc)[:120]}", flush=True)
                q = {"version": Q.QUOTES_VERSION, "want": b["quote_want"], "fingerprint": None, "quotes": {}}
            src = {**src, "quotes": q}
            Q.apply(b["payload"], q)
            built[sym] = {**b, "sources": src, "prior": prior}
            st = {s["key"]: s["status"] for s in b["payload"]["steps"]}
            rows.append({"symbol": sym, "sector": u["tickers"][sym]["sector"], "steps": st,
                         "reasons": {s["key"]: s["absent"] for s in b["payload"]["steps"] if s["status"] == "absent"},
                         "segment_reason": (src.get("segments") or {}).get("reason"), "risk_reason": (src.get("risks") or {}).get("reason"),
                         "margin_measure": (src.get("margins") or {}).get("measure"), "margin_reason": (src.get("margins") or {}).get("reason"),
                         "steps_shown": b["steps_shown"], "quarter_check": b.get("quarter_check")})
            if i % 50 == 0:
                print(f"  {i}/{len(symbols)} built", flush=True)
    finally:
        await edgar.close()

    spent = 0.0
    if story and write:
        spent = await WS.run_stories(built, today, max(0.0, WS.NIGHTLY_STORY_CAP_USD - quote_spend))
    else:
        await WS.reuse_stories(built)
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
    print(f"  SEC reads failed: {sec_failed}; story spend ${spent:.2f}; quote spend ${quote_spend:.2f}", flush=True)
    if report:
        with open(report, "w") as fh:
            json.dump({"run_at": datetime.now(timezone.utc).isoformat(), "today": today.isoformat(), "counts": counts, "stocks": rows}, fh, default=str, indent=1)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
