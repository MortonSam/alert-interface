"""Release EPS: for tickers that reported a quarter XBRL does not hold yet, read the quarter's GAAP diluted EPS from the
earnings release (the Item 2.02 8-K's EX-99.1) and store it in release_eps with the filing as its receipt. Dry run by
default; --write stores. The nightly runs it with --write for every report in the last LOOKBACK_DAYS without a stored row, and
for the latest report of any ticker whose P/E is missing because XBRL lags it.

    python -m app.scripts.seed_release_eps MU                 # dry run for one ticker
    python -m app.scripts.seed_release_eps MU --write
    python -m app.scripts.seed_release_eps --symbols=HPE,PANW         # the same, as a flag
    python -m app.scripts.seed_release_eps --due --write      # every recent report without a row (the nightly step)
    python -m app.scripts.seed_release_eps --due --no-model   # the pattern parser alone (nothing stores: both readers must agree)

Two readers. The pattern parser (valuation.parse_release_eps) and the model (services/release_reader, Sonnet, with its verbatim quote
verified by code) read every exhibit; a figure is stored only when both agree to the cent. A disagreement, a rejected quote or a
reader that read nothing records the report as unread with both readings, and the morning digest lists it.
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields
from app.services.valuation import implausible, parse_release_eps, year_over_year_note
from app.services import release_reader as R

STEP_LABEL = "Release EPS (8-K exhibits)"
LOOKBACK_DAYS = 45
MATCH_DAYS = 5          # the 8-K is filed within this many days of the report


def exhibit_candidates(texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pure: the documents worth parsing, press-release exhibits first (EX-99.x by name), then the rest by length; index files,
    bylaws and the cover 8-K last or never."""
    docs = [(n, t) for n, t in texts if t and len(t) > 500 and "index" not in n.lower() and not re.search(r"by-?laws|bylaws", n.lower())]
    press = [d for d in docs if re.search(r"ex(?:hibit)?[-_.]?99|99[-_.]?[1-9]|ex99", d[0].lower())]
    rest = sorted((d for d in docs if d not in press), key=lambda x: -len(x[1]))
    return press + rest


def exhibit_text(texts: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Pure: the first press-release exhibit (compatibility: callers that want one document)."""
    cands = exhibit_candidates(texts)
    return cands[0] if cands else None


async def run(argv: list[str]) -> int:
    write, due = "--write" in argv, "--due" in argv
    symbols = [a.upper() for a in argv if not a.startswith("--")]
    flagged = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)     # --symbols=MU,HPE
    if flagged:
        symbols += [x.strip().upper() for x in flagged.split(",") if x.strip()]
    today = date.today()
    async with ScriptSessionLocal() as s:
        if due:
            # every report in the last LOOKBACK_DAYS without a stored figure, plus the latest report of any ticker whose P/E is
            # missing because XBRL lags that report (the SEC's company-facts feed runs behind some filers for months)
            rows = (await s.execute(text("""
                SELECT DISTINCT symbol, event_date FROM (
                    SELECT t.symbol, e.event_date FROM events e JOIN tickers t ON t.id = e.ticker_id
                    LEFT JOIN release_eps r ON r.symbol = t.symbol AND r.report_date = e.event_date
                    WHERE e.event_type = 'earnings' AND t.is_active AND e.event_date <= :t AND e.event_date >= :since
                      AND (e.is_confirmed OR e.eps_actual IS NOT NULL) AND r.id IS NULL
                    UNION
                    SELECT p.symbol, p.latest_report FROM (SELECT DISTINCT ON (symbol) symbol, status, reason, latest_report FROM pe_snapshots ORDER BY symbol, as_of_date DESC) p
                    LEFT JOIN release_eps r ON r.symbol = p.symbol AND r.report_date = p.latest_report
                    WHERE p.status = 'missing' AND p.reason LIKE '%newer than XBRL%' AND p.latest_report IS NOT NULL AND r.id IS NULL) x ORDER BY symbol"""),
                {"t": today, "since": today - timedelta(days=LOOKBACK_DAYS)})).all()
        else:
            rows = (await s.execute(text("""
                SELECT symbol, max(d) FROM (
                    SELECT t.symbol, e.event_date AS d FROM events e JOIN tickers t ON t.id = e.ticker_id
                    WHERE t.symbol = ANY(:syms) AND e.event_type = 'earnings' AND e.event_date <= :t AND (e.is_confirmed OR e.eps_actual IS NOT NULL)
                    UNION ALL
                    SELECT t.symbol, hr.event_date FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
                    WHERE t.symbol = ANY(:syms) AND hr.event_type = 'earnings' AND hr.event_date <= :t) x GROUP BY symbol ORDER BY symbol"""), {"syms": symbols, "t": today})).all()
    async with ScriptSessionLocal() as s:
        # for the plausibility guard: the close on (or just before) each report date and the stored adjusted EPS for the report (both refuse);
        # the same quarter a year earlier from XBRL (a digest warning only)
        closes = {}
        adjusted = {}
        priors = {}
        for sym, report_date in rows:
            c = (await s.execute(text("SELECT close FROM price_bars_shadow WHERE symbol = :s AND date <= :d ORDER BY date DESC LIMIT 1"), {"s": sym, "d": report_date})).scalar()
            closes[(sym, report_date)] = float(c) if c is not None else None
            adj = (await s.execute(text("""SELECT e.eps_actual FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s AND e.event_type = 'earnings'
                AND e.eps_actual IS NOT NULL AND e.event_date BETWEEN :a AND :b ORDER BY abs(e.event_date - :d) LIMIT 1"""),
                                   {"s": sym, "a": report_date - timedelta(days=3), "b": report_date + timedelta(days=3), "d": report_date})).scalar()
            adjusted[(sym, report_date)] = float(adj) if adj is not None else None
            pr = (await s.execute(text("""SELECT eps FROM eps_quarters WHERE symbol = :s AND period_end BETWEEN :a AND :b ORDER BY period_end DESC LIMIT 1"""),
                                  {"s": sym, "a": report_date - timedelta(days=365 + 60), "b": report_date - timedelta(days=365 - 30)})).scalar()
            priors[(sym, report_date)] = float(pr) if pr is not None else None
    print(f"{STEP_LABEL}: {len(rows)} report(s) to read ({'write' if write else 'dry run'})", flush=True)
    edgar = EdgarClient()
    stored = parsed = unread = 0
    results = []
    yoy_warnings = []
    disagreements = []
    model_costs: list[float] = []
    use_model = "--no-model" not in argv
    model_client = None
    if use_model:
        from app.config import settings
        if settings.anthropic_api_key:
            from app.services.anthropic_client import AnthropicClient
            model_client = AnthropicClient()
        else:
            print("  no Anthropic key: the model reader is off, so nothing can store (both readers must agree)", flush=True)
    try:
        for sym, report_date in rows:
            try:
                cik = await edgar.get_cik(sym)
                if not cik:
                    print(f"  {sym}: no CIK"); unread += 1; continue
                recs = [r for r in await edgar.get_all_8k_records(cik) if "2.02" in (r.get("items") or "")
                        and abs((date.fromisoformat(r["filing_date"]) - report_date).days) <= MATCH_DAYS]
                if not recs:
                    print(f"  {sym} {report_date}: no Item 2.02 8-K within {MATCH_DAYS} days"); unread += 1; continue
                ex, hit, rec = None, None, recs[0]
                for rec in recs:                              # a company may file more than one Item 2.02 8-K that week (DTE Gas beside DTE Energy)
                    texts = await edgar.filing_texts(cik, rec["accession"], rec.get("primary_document") or rec.get("primaryDocument", ""))
                    for cand in exhibit_candidates(texts):   # a subsidiary's release may sit beside the issuer's; the first that reads wins
                        hit = parse_release_eps(cand[1], report_date)
                        if hit:
                            ex = cand
                            break
                    if hit:
                        break
                # the second reader: the model reads the same exhibit the pattern parser read (or the first press exhibit when it read none)
                model = None
                exhibit_for_model = ex[1] if ex else ""
                if model_client is not None:
                    try:
                        cands = exhibit_candidates(texts)
                        exhibit_for_model = ex[1] if ex else (cands[0][1] if cands else "")
                        model = await R.model_read(model_client, exhibit_for_model, report_date)
                        if model.get("cost_usd") is not None:
                            model_costs.append(model["cost_usd"])
                    except Exception as exc:
                        print(f"  {sym} {report_date}: model reader failed: {redact(exc)[:100]}")
                        model = None
                if not hit and not (model and model.get("eps") is not None):
                    print(f"  {sym} {report_date}: 8-K {', '.join(r['accession'] for r in recs)}: no GAAP diluted EPS read" + ("" if model else "; model read nothing")); unread += 1; continue
                figure, note = R.decide(hit, model, (ex[1] if ex else exhibit_for_model) if model_client is not None else "")
                if model_client is not None and figure is None:
                    cost = f" (model ${model['cost_usd']:.4f})" if model and model.get("cost_usd") is not None else ""
                    print(f"  {sym} {report_date}: UNREAD, {note}{cost}")
                    disagreements.append(f"{sym} {report_date}: {note}")
                    unread += 1; continue
                if model_client is None and not hit:
                    unread += 1; continue
                why = implausible(hit["eps"], closes.get((sym, report_date)), adjusted.get((sym, report_date)))
                if why:
                    print(f"  {sym} {report_date}: read {hit['eps']:+.2f} ({hit['how']}) but unread: {why}"); unread += 1; continue
                if model_client is None:
                    print(f"  {sym} {report_date}: pattern {hit['eps']:+.2f} ({hit['how']}); model reader off: not stored")
                yoy = year_over_year_note(hit["eps"], priors.get((sym, report_date)))
                if yoy:
                    yoy_warnings.append(f"{sym} {report_date}: {yoy}")
                    print(f"  {sym} {report_date}: year-over-year warning: {yoy}")
                parsed += 1
                cost = f"; model ${model['cost_usd']:.4f}, {model['input_tokens']} in / {model['output_tokens']} out" if model and model.get("cost_usd") is not None else ""
                print(f"  {sym} {report_date}: GAAP diluted EPS {hit['eps']:+.2f} ({hit['how']}; quarter ended {hit['period_end']}) from {rec['accession']} {ex[0]}; {note}{cost}")
                print(f"      evidence: {hit['evidence'][:200]}")
                results.append({"symbol": sym, "report_date": report_date.isoformat(), "eps": hit["eps"], "period_end": hit["period_end"].isoformat() if hit["period_end"] else None, "accession": rec["accession"]})
                if write and model_client is not None:
                    async with ScriptSessionLocal() as s:
                        await s.execute(text("""
                            INSERT INTO release_eps (symbol, report_date, period_end, diluted_eps_gaap, how, evidence, accession, exhibit, filed_on)
                            VALUES (:s, :d, :pe, :eps, :how, :ev, :acc, :ex, :filed)
                            ON CONFLICT (symbol, report_date) DO UPDATE SET period_end = EXCLUDED.period_end, diluted_eps_gaap = EXCLUDED.diluted_eps_gaap,
                                how = EXCLUDED.how, evidence = EXCLUDED.evidence, accession = EXCLUDED.accession, exhibit = EXCLUDED.exhibit, filed_on = EXCLUDED.filed_on, parsed_at = now()"""),
                            {"s": sym, "d": report_date, "pe": hit["period_end"], "eps": hit["eps"], "how": hit["how"], "ev": hit["evidence"][:2000], "acc": rec["accession"], "ex": ex[0][:120],
                             "filed": date.fromisoformat(rec["filing_date"])})
                        await s.commit()
                    stored += 1
            except Exception as exc:
                print(f"  {sym} {report_date}: failed: {redact(exc)[:120]}"); unread += 1
    finally:
        await edgar.close()
    total_cost = round(sum(model_costs), 4)
    print(f"  read {parsed} (both readers agree), stored {stored}, unread {unread}, reader disagreements {len(disagreements)}; model reads {len(model_costs)}, "
          f"cost ${total_cost:.4f} total, ${(total_cost / len(model_costs)) if model_costs else 0:.4f} per release" + ("" if write else "; dry run, nothing written"))
    for d in disagreements:
        print(f"    disagreement: {d[:300]}")
    if write and due:
        await record_step_fields(STEP_LABEL, {"reports": len(rows), "read": parsed, "stored": stored, "unread": unread, "rows": results[:50], "yoy_warnings": yoy_warnings[:20],
                                              "disagreements": disagreements[:30], "model_reads": len(model_costs), "model_cost_usd": total_cost, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
