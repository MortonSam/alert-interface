"""Release EPS: for tickers that reported a quarter XBRL does not hold yet, read the quarter's GAAP diluted EPS from the
earnings release (the Item 2.02 8-K's EX-99.1) and store it in release_eps with the filing as its receipt. Dry run by
default; --write stores. The nightly runs it with --write for every report in the last LOOKBACK_DAYS without a stored row, and
for the latest report of any ticker whose P/E is missing because XBRL lags it.

    python -m app.scripts.seed_release_eps MU                 # dry run for one ticker
    python -m app.scripts.seed_release_eps MU --write
    python -m app.scripts.seed_release_eps --due --write      # every recent report without a row (the nightly step)
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
from app.services.valuation import parse_release_eps

STEP_LABEL = "Release EPS (8-K exhibits)"
LOOKBACK_DAYS = 45
MATCH_DAYS = 5          # the 8-K is filed within this many days of the report


def exhibit_text(texts: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Pure: (name, text) of the EX-99.1 press release among a filing's documents, else the longest exhibit."""
    docs = [(n, t) for n, t in texts if t and len(t) > 500 and "index" not in n.lower()]
    for name, t in docs:
        if re.search(r"ex(?:hibit)?[-_.]?99|99[-_.]?1|ex99", name.lower()):
            return name, t
    cands = docs
    return max(cands, key=lambda x: len(x[1])) if cands else None


async def run(argv: list[str]) -> int:
    write, due = "--write" in argv, "--due" in argv
    symbols = [a.upper() for a in argv if not a.startswith("--")]
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
    print(f"{STEP_LABEL}: {len(rows)} report(s) to read ({'write' if write else 'dry run'})", flush=True)
    edgar = EdgarClient()
    stored = parsed = unread = 0
    results = []
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
                rec = recs[0]
                texts = await edgar.filing_texts(cik, rec["accession"], rec.get("primary_document") or rec.get("primaryDocument", ""))
                ex = exhibit_text(texts)
                hit = parse_release_eps(ex[1], report_date) if ex else None
                if not hit:
                    print(f"  {sym} {report_date}: 8-K {rec['accession']}: no GAAP diluted EPS read"); unread += 1; continue
                parsed += 1
                print(f"  {sym} {report_date}: GAAP diluted EPS {hit['eps']:+.2f} ({hit['how']}; quarter ended {hit['period_end']}) from {rec['accession']} {ex[0]}")
                print(f"      evidence: {hit['evidence'][:200]}")
                results.append({"symbol": sym, "report_date": report_date.isoformat(), "eps": hit["eps"], "period_end": hit["period_end"].isoformat() if hit["period_end"] else None, "accession": rec["accession"]})
                if write:
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
    print(f"  read {parsed}, stored {stored}, unread {unread}" + ("" if write else "; dry run, nothing written"))
    if write and due:
        await record_step_fields(STEP_LABEL, {"reports": len(rows), "read": parsed, "stored": stored, "unread": unread, "rows": results[:50], "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
