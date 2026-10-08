"""Discover news step: Finnhub company news for every active S&P 500 ticker plus general market news, deduplicated and kept for the
last 24 hours (news_stories), and each ticker's quote (quote_snapshots) for "Today's biggest movers". Runs in the nightly and,
from startup's news loop, hourly through the US session. Paced below the process-wide Finnhub limit (NEWS_FINNHUB_RPM, default
40) so a run never crowds out the site's own quote requests.

Usage: python -m app.scripts.refresh_news [--symbols=AAPL,MSFT] [--no-quotes]
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import finnhub_client
from app.services.finnhub_client import FinnhubClient
from app.services.news import FRESH_HOURS, STEP_LABEL, dedupe
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields

FAILED_SHARE_LIMIT = 0.10        # more than this share of requests failing fails the step (and hides the sections)


async def _fetch(client: FinnhubClient, symbols: list[str], quotes: bool) -> tuple[list[tuple[str, dict]], dict[str, dict], list[str]]:
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=1)).isoformat()
    raw: list[tuple[str, dict]] = []
    snaps: dict[str, dict] = {}
    failed: list[str] = []
    try:
        raw += [("general", item) for item in (await client.get_general_news()) or []]
    except Exception as exc:
        failed.append(f"general news: {redact(exc)[:80]}")
    for sym in symbols:
        try:
            for item in (await client.get_company_news(sym, since, today.isoformat())) or []:
                item = {**item, "related": ",".join(filter(None, {sym, *(item.get("related") or "").split(",")}))}
                raw.append(("company", item))
        except Exception as exc:
            failed.append(f"{sym} news: {redact(exc)[:60]}")
        if quotes:
            try:
                q = await client.get_quote(sym)
                ts = int(q["t"]) if q.get("t") else None
                snaps[sym] = {"price": float(q["c"]) if q.get("c") else None, "change_pct": float(q["dp"]) if q.get("dp") is not None else None,
                              "prev_close": float(q["pc"]) if q.get("pc") else None,
                              "quote_time": datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None}
            except Exception as exc:
                failed.append(f"{sym} quote: {redact(exc)[:60]}")
    return raw, snaps, failed


async def run(argv: list[str]) -> int:
    finnhub_client.REQUESTS_PER_MINUTE = int(os.environ.get("NEWS_FINNHUB_RPM", "40"))
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    quotes = "--no-quotes" not in argv
    t0 = time.time()
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        universe = list((await s.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
    symbols = [x.strip().upper() for x in only.split(",")] if only else universe
    client = FinnhubClient()
    try:
        raw, snaps, failed = await _fetch(client, symbols, quotes)
    finally:
        await client.close()
    stories = dedupe(raw, now, set(universe))
    requests = 1 + len(symbols) * (2 if quotes else 1)
    exit_code = 0
    try:
        async with ScriptSessionLocal() as s:
            for st in stories.values():
                await s.execute(text("""
                    INSERT INTO news_stories (url, headline, source, published_at, related, category, fetched_at)
                    VALUES (:url, :headline, :source, :published_at, :related, :category, now())
                    ON CONFLICT (url) DO UPDATE SET
                        related = ARRAY(SELECT DISTINCT unnest(news_stories.related || EXCLUDED.related) ORDER BY 1),
                        category = CASE WHEN EXCLUDED.category = 'company' THEN 'company' ELSE news_stories.category END,
                        fetched_at = now()"""), st)
            pruned = (await s.execute(text("DELETE FROM news_stories WHERE published_at < :c"), {"c": now - timedelta(hours=FRESH_HOURS)})).rowcount
            for sym, q in snaps.items():
                await s.execute(text("""
                    INSERT INTO quote_snapshots (symbol, price, change_pct, prev_close, quote_time, captured_at)
                    VALUES (:symbol, :price, :change_pct, :prev_close, :quote_time, now())
                    ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, change_pct = EXCLUDED.change_pct,
                        prev_close = EXCLUDED.prev_close, quote_time = EXCLUDED.quote_time, captured_at = now()"""), {"symbol": sym, **q})
            await s.commit()
    except Exception as exc:          # a database write failure fails the step: the sections hide rather than show a partial day
        print(f"  write failed: {redact(exc)}")
        failed.append(f"database: {redact(exc)[:80]}")
        exit_code = 1
        pruned = 0
    if len(failed) > FAILED_SHARE_LIMIT * requests:
        exit_code = 1
    seconds = round(time.time() - t0, 1)
    print(f"News: {len(stories)} stories from {len(raw)} items ({sum(1 for s in stories.values() if s['related'])} about S&P 500 companies), "
          f"{len(snaps)} quotes, {len(failed)} failed request(s), {pruned} stories older than {FRESH_HOURS}h pruned, {seconds}s")
    for f in failed[:20]:
        print(f"  failed: {f}")
    await record_step_fields(STEP_LABEL, {"exit": exit_code, "at": datetime.now(timezone.utc).isoformat(), "seconds": seconds,
                                          "stories": len(stories), "quotes": len(snaps), "failed": len(failed), "failed_sample": failed[:10]})
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
