"""Confirm earnings dates from the companies' own words (services/report_date_reader): every 8-K exhibit of the last DAYS days,
every press release we ingest (Finnhub company news, one call per ticker, and the stored news_stories) and the company's IR feed
items are read by the pattern reader; where it names a
date the model reads the same passage, and a date counts only when both agree and it is in the future. Dry run by default:
prints what each active ticker's stored date is, what the readers found and what a write would do. Writes only with --write AND
CONFIRMATION_READER_WRITE=true in the environment (the nightly step passes --write; the variable holds it until Sam's go).

    python -m app.scripts.confirm_report_dates                    # dry run, every active ticker, last 45 days
    python -m app.scripts.confirm_report_dates --symbols=TSLA,JPM --days=60
    python -m app.scripts.confirm_report_dates --no-model          # the pattern reader alone (nothing can confirm)
    CONFIRMATION_READER_WRITE=true python -m app.scripts.confirm_report_dates --write

A write: the ticker's stored future earnings event nearest the confirmed date (within SAME_REPORT_DAYS) moves to it, confirmed,
with the evidence note; a ticker with no stored future date gets a new confirmed event. The evidence record goes to
system_metadata report_confirmation:{SYM}:{DATE}. Ivy's rule is unchanged: she still acts on confirmed dates only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services import report_date_reader as R
from app.services.earnings_calendar import SAME_REPORT_DAYS
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.report_announcements import names_issuer
from app.services.step_outcomes import record_step_fields
from app.services.system_metadata_service import set_value

STEP_LABEL = "Report date confirmations (reader)"
DAYS = 45
WRITE_VAR = "CONFIRMATION_READER_WRITE"
MAX_FILINGS_PER_TICKER = 6
TICKER_TIMEOUT_S = 120            # a ticker's filings, its feed, or one model read, before the run moves on (the 2026-10-12 dry run stalled at one filer)
MAX_FEED_PAGES = 4
EVIDENCE_KEY = "report_confirmation:{sym}:{day}"


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


def writes_allowed(argv: list[str], env: dict | None = None) -> bool:
    """Pure: --write and the environment variable together; either alone is a dry run."""
    env = os.environ if env is None else env
    return "--write" in argv and (env.get(WRITE_VAR) or "").strip().lower() in ("1", "true", "yes")


async def targets(only: set[str] | None) -> list[dict]:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT t.id, t.symbol, t.name, f.feed_url FROM tickers t
            LEFT JOIN ir_feeds f ON f.symbol = t.symbol AND f.classification = 'press_releases' AND f.feed_url IS NOT NULL
            WHERE t.is_active ORDER BY t.symbol"""))).mappings().all()
    return [dict(r) for r in rows if not only or r["symbol"] in only]


async def stored_future(symbols: list[str], today: date) -> dict[str, list[dict]]:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT t.symbol, e.event_date, e.is_confirmed, e.confirmation_note, e.report_timing
            FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE e.event_type = 'earnings' AND e.event_date >= :t AND t.symbol = ANY(:s)
            ORDER BY e.event_date"""), {"t": today, "s": symbols})).mappings().all()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(dict(r))
    return out


async def finnhub_news(finnhub, symbol: str, since: date, today: date) -> list[dict]:
    """The company's news items from Finnhub (the wire copy of its IR releases lands here), one call per ticker."""
    items = await finnhub.get_company_news(symbol, since.isoformat(), today.isoformat())
    out = []
    for it in items or []:
        published = date.fromtimestamp(it["datetime"]).isoformat() if it.get("datetime") else "?"
        out.append({"kind": "press release", "reference": it.get("url") or "", "published": published, "headline": str(it.get("headline", "")),
                    "text": f"{it.get('headline', '')}. {it.get('summary', '')}"})
    return out


async def stored_news(symbol: str, since: date) -> list[dict]:
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT url, headline, summary, published_at FROM news_stories
            WHERE :sym = ANY(related) AND published_at >= :since ORDER BY published_at DESC LIMIT 60"""), {"sym": symbol, "since": since})).mappings().all()
    return [dict(r) for r in rows]


async def edgar_texts(edgar: EdgarClient, symbol: str, since: date, today: date) -> list[dict]:
    """[{kind, reference, published, text}] for every document of the ticker's 8-Ks filed in the window, newest first."""
    cik = await edgar.get_cik(symbol)
    if not cik:
        return []
    recs = [r for r in await edgar.get_all_8k_records(cik) if since.isoformat() <= r.get("filing_date", "") <= today.isoformat()]
    recs.sort(key=lambda r: r["filing_date"], reverse=True)
    out = []
    for r in recs[:MAX_FILINGS_PER_TICKER]:
        items = ", ".join(i.strip() for i in (r.get("items") or "").split(",") if i.strip())
        for name, t in await edgar.filing_texts(cik, r["accession"], r.get("primary_document") or ""):
            out.append({"kind": "8-K exhibit", "reference": f"Item {items} {name}".strip(), "published": r["filing_date"], "text": t, "accession": r["accession"]})
    return out


async def feed_texts(http: httpx.AsyncClient, feed_url: str, issuer: str | None, symbol: str, today: date) -> list[dict]:
    """The company's own press-release items that look like a results-date announcement, with their release pages."""
    from app.services import ir_feeds as F
    body = await F.fetch_allowed(http, feed_url)
    if not body:
        return []
    out = []
    for it in F.candidates(F.parse_items(body, feed_url), issuer, symbol)[:MAX_FEED_PAGES]:
        page = await F.fetch_allowed(http, it.get("link") or "") if it.get("link") else None
        t = F.clean(page) if page else ""
        out.append({"kind": "IR feed", "reference": it.get("link") or feed_url, "published": (it.get("pubDate") or it.get("published") or "")[:10] or "?",
                    "text": f"{it.get('title', '')}. {t or it.get('description', '')}"})
    return out


def classify(day: date, stored: list[dict]) -> tuple[str, dict | None]:
    """Pure: what a write would do against the ticker's stored future dates: 'confirms' (the same day, estimated), 'already'
    (confirmed on that day), 'changes' (an estimated date within SAME_REPORT_DAYS moves), 'contradicts' (a confirmed date within
    SAME_REPORT_DAYS differs), or 'new' (nothing stored for that report)."""
    same = next((e for e in stored if e["event_date"] == day), None)
    if same:
        return ("already" if same["is_confirmed"] else "confirms"), same
    near = [e for e in stored if abs((e["event_date"] - day).days) < SAME_REPORT_DAYS]
    if near:
        e = min(near, key=lambda x: abs((x["event_date"] - day).days))
        return ("contradicts" if e["is_confirmed"] else "changes"), e
    return "new", None


async def write_confirmation(ticker_id, symbol: str, day: date, timing: str, note: str, evidence: dict, stored: list[dict], now: datetime) -> str:
    async with ScriptSessionLocal() as s:
        kind, target = classify(day, stored)
        if kind == "already":
            return "already confirmed"
        if kind in ("changes", "confirms", "contradicts") and target is not None:
            ev = (await s.execute(select(Event).where(Event.ticker_id == ticker_id, Event.event_type == EventType.EARNINGS, Event.event_date == target["event_date"]))).scalars().first()
            if ev is not None:
                ev.event_date, ev.is_confirmed, ev.source, ev.confirmation_note, ev.checked_at = day, True, DataSource.EDGAR, note, now
                ev.unresolved_since, ev.sources_checked = None, None
                if timing != "unknown":
                    ev.report_timing, ev.report_timing_source = timing, "company"
        else:
            s.add(Event(ticker_id=ticker_id, event_type=EventType.EARNINGS, event_date=day, title="Earnings", source=DataSource.EDGAR, is_confirmed=True,
                        confirmation_note=note, checked_at=now, metadata_={}, report_timing=timing, report_timing_source="company" if timing != "unknown" else "unknown"))
        await set_value(s, EVIDENCE_KEY.format(sym=symbol, day=day.isoformat()), json.dumps(evidence))
        await s.commit()
    return kind


async def main(argv: list[str]) -> int:
    today = date.today()
    days = int(_arg(argv, "days") or DAYS)
    since = today - timedelta(days=days)
    only = {x.strip().upper() for x in (_arg(argv, "symbols") or "").split(",") if x.strip()} or None
    write = writes_allowed(argv)
    use_model = "--no-model" not in argv
    tickers = await targets(only)
    stored = await stored_future([t["symbol"] for t in tickers], today)
    print(f"{STEP_LABEL}: {len(tickers)} ticker(s), filings and releases since {since}, {'WRITE' if write else 'dry run'}{'' if use_model else ', pattern reader only'}", flush=True)
    client = None
    if use_model:
        from app.config import settings
        if settings.anthropic_api_key:
            from app.services.anthropic_client import AnthropicClient
            client = AnthropicClient()
        else:
            print("  no Anthropic key: the model reader is off, so nothing can confirm", flush=True)
    edgar = EdgarClient()
    finnhub = None
    if "--no-finnhub" not in argv:
        from app.services.finnhub_client import FinnhubClient
        finnhub = FinnhubClient()
    http = httpx.AsyncClient(headers={"User-Agent": "alert-interface report date reader (sammyjmorton@gmail.com)"}, timeout=15.0)
    now = datetime.now(timezone.utc)
    found: list[dict] = []
    disagreements: list[str] = []
    by_kind: dict[str, int] = {}
    docs_read = model_reads = 0
    cost = 0.0
    errors: list[str] = []
    t0 = time.time()
    try:
        for i, t in enumerate(tickers):
            sym = t["symbol"]
            try:
                docs = await asyncio.wait_for(edgar_texts(edgar, sym, since, today), TICKER_TIMEOUT_S)    # one slow filer never stalls the run
                docs += [{"kind": "press release", "reference": n["url"], "published": n["published_at"].date().isoformat() if n.get("published_at") else "?",
                          "headline": n["headline"], "text": f"{n['headline']}. {n.get('summary') or ''}"} for n in await stored_news(sym, since)]
                if finnhub is not None:
                    try:
                        docs += await finnhub_news(finnhub, sym, since, today)
                    except Exception as exc:
                        errors.append(f"{sym}: Finnhub news: {redact(exc)[:100]}")
                if t.get("feed_url"):
                    docs += await asyncio.wait_for(feed_texts(http, t["feed_url"], t.get("name"), sym, today), TICKER_TIMEOUT_S)
                docs_read += len(docs)
                seen_days: set[date] = set()
                if "--screen" in argv:                    # diagnosis: every results sentence with a future date, accepted or not
                    for d in docs:
                        for s in R.screen(d["text"], today):
                            print(f"  screen {sym} {d['kind']} {d['published']}: {s[:220]}", flush=True)
                for d in docs:
                    # a press release counts only when its headline names the issuer: Ares Capital's release is not Ares Management's,
                    # Goldman Sachs BDC's is not Goldman Sachs', and an article about PNC confirms nothing for the banks it mentions
                    if d["kind"] == "press release" and not names_issuer(d.get("headline") or d["text"], t.get("name") or sym):
                        continue
                    hit = R.read_report_date(d["text"], today)
                    if hit is None or hit.day in seen_days:
                        continue
                    seen_days.add(hit.day)
                    model = None
                    if client is not None:
                        try:
                            model = await asyncio.wait_for(R.model_read(client, R.passage(d["text"], hit.sentence), today), TICKER_TIMEOUT_S)
                            model_reads += 1
                            cost += model.get("cost_usd") or 0.0
                        except Exception as exc:
                            errors.append(f"{sym}: model reader failed: {redact(exc)[:100]}")
                    day, note = R.decide(hit, model, d["text"], today)
                    kind, target = classify(hit.day, stored.get(sym, []))
                    rec = {"symbol": sym, "date": hit.day.isoformat(), "timing": hit.timing, "source_kind": d["kind"], "reference": d["reference"], "published": d["published"],
                           "quote": hit.sentence[:300], "readers": note, "confirmed": day is not None, "would": kind, "stored": target["event_date"].isoformat() if target else None,
                           "read_at": now.isoformat(), "computation_version": R.READER_VERSION}
                    found.append(rec)
                    if day is None and model is not None:
                        disagreements.append(f"{sym} {hit.day.isoformat()}: {note}")
                    if day is not None:
                        by_kind[kind] = by_kind.get(kind, 0) + 1
                        cal_note = R.confirmation_note(d["kind"], d["reference"], d["published"], hit.sentence[:200])
                        if write:
                            did = await write_confirmation(t["id"], sym, day, hit.timing, cal_note, rec, stored.get(sym, []), now)
                            rec["written"] = did
                    print(f"  {sym}: {d['kind']} {d['published']} -> {hit.day} ({hit.timing}); {note}; would {kind}" + (f" (stored {target['event_date']})" if target else ""), flush=True)
            except Exception as exc:
                errors.append(f"{sym}: {redact(exc)[:120]}")
            if i % 50 == 0:
                print(f"  ... {i}/{len(tickers)} tickers, {docs_read} documents, {model_reads} model reads, ${cost:.3f}, {time.time() - t0:.0f}s", flush=True)
    finally:
        await edgar.close()
        await http.aclose()
    confirmed = [f for f in found if f["confirmed"]]
    summary = {"tickers": len(tickers), "documents": docs_read, "candidates": len(found), "confirmed": len(confirmed), "would": by_kind,
               "disagreements": len(disagreements), "model_reads": model_reads, "model_cost_usd": round(cost, 4), "write": write, "errors": len(errors), "seconds": round(time.time() - t0)}
    print("\n" + json.dumps(summary))
    for dline in disagreements:
        print(f"    disagreement: {dline[:300]}")
    for e in errors[:20]:
        print(f"    error: {e}")
    if "--write" in argv:          # the nightly step records its outcome whether or not the variable allowed the write
        await record_step_fields(STEP_LABEL, {**summary, "writes_enabled": write, "found": found[:200], "disagreement_lines": disagreements[:50], "error_lines": errors[:20],
                                              "note": None if write else f"dry run: set {WRITE_VAR}=true to write confirmations", "error": None})
    out = os.environ.get("CONFIRM_REPORT_DATES_OUT")
    if out:
        with open(out, "w") as fh:
            json.dump({"summary": summary, "found": found, "disagreements": disagreements, "errors": errors}, fh, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
