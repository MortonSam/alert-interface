"""IR feed discovery, phase 1: for every active ticker, the company's web domain from its Intrinio profile, then a fixed set
of feed paths on the usual investor-relations hosts, probed concurrently; the first feed that answers with items is stored
(ir_feeds). Nothing is read from the feeds yet beyond counting items; phase 2 runs the announcement detector over them.

    python -m app.scripts.discover_ir_feeds                 # tickers with no row yet
    python -m app.scripts.discover_ir_feeds --all           # every active ticker again
    python -m app.scripts.discover_ir_feeds --symbols=MU,FDX
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.intrinio_client import IntrinioClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "IR feed discovery"
HOSTS = ("investors.{d}", "investor.{d}", "ir.{d}", "{d}", "www.{d}")
PATHS = ("/rss/news-releases.xml", "/rss/pressrelease.aspx", "/rss/news.xml", "/feed", "/news/rss", "/press-releases/rss", "/rss/events.xml", "/rss.xml")
CONCURRENCY = 16
TIMEOUT = 8.0
UA = "alert-interface IR feed discovery (sammyjmorton@gmail.com)"
_ITEM = re.compile(r"<(item|entry)\b", re.I)


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    return host[4:] if host.startswith("www.") else host or None


def feed_kind(body: str) -> str | None:
    head = body[:2000].lower()
    if "<rss" in head or "<rdf" in head:
        return "rss"
    if "<feed" in head:
        return "atom"
    return None


async def probe(client: httpx.AsyncClient, url: str) -> tuple[str, int] | None:
    try:
        r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
    except Exception:
        return None
    if r.status_code != 200 or len(r.text) < 100:
        return None
    kind = feed_kind(r.text)
    if not kind:
        return None
    return kind, len(_ITEM.findall(r.text))


async def find_feed(client: httpx.AsyncClient, domain: str) -> tuple[str | None, str | None, int, int]:
    """(feed_url, kind, items, probes) for a domain: the first candidate that answers with a feed holding items."""
    probes = 0
    for host in HOSTS:
        for path in PATHS:
            url = f"https://{host.format(d=domain)}{path}"
            probes += 1
            got = await probe(client, url)
            if got and got[1] > 0:
                return url, got[0], got[1], probes
    return None, None, 0, probes


async def run(argv: list[str]) -> int:
    refresh_all = "--all" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    only_set = {x.strip().upper() for x in only.split(",")} if only else None
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("SELECT t.symbol, f.symbol IS NOT NULL AS has_row FROM tickers t LEFT JOIN ir_feeds f ON f.symbol = t.symbol WHERE t.is_active ORDER BY t.symbol"))).all()
    symbols = [r[0] for r in rows if (only_set and r[0] in only_set) or (not only_set and (refresh_all or not r[1]))]
    print(f"{STEP_LABEL}: {len(symbols)} ticker(s) to probe", flush=True)
    intrinio = IntrinioClient()
    domains: dict[str, str | None] = {}
    try:
        for sym in symbols:
            try:
                body = await intrinio._get(f"/companies/{sym}", {})
                domains[sym] = domain_of(body.get("company_url"))
            except Exception as exc:
                print(f"  [WARN] {sym}: {redact(exc)[:100]}", flush=True)
                domains[sym] = None
    finally:
        await intrinio.close()
    sem = asyncio.Semaphore(CONCURRENCY)
    results: dict[str, tuple] = {}
    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        async def one(sym: str):
            d = domains.get(sym)
            if not d:
                results[sym] = (None, None, None, 0, 0); return
            async with sem:
                url, kind, items, probes = await find_feed(client, d)
            results[sym] = (d, url, kind, items, probes)
            if url:
                print(f"  {sym}: {url} ({kind}, {items} items)", flush=True)
        await asyncio.gather(*(one(sym) for sym in symbols))
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        for sym, (d, url, kind, items, probes) in results.items():
            await s.execute(text("""
                INSERT INTO ir_feeds (symbol, domain, feed_url, kind, items, probed, discovered_at, last_ok_at)
                VALUES (:s, CAST(:d AS text), CAST(:u AS text), CAST(:k AS varchar), CAST(:i AS integer), :p, :now, CAST(:ok AS timestamptz))
                ON CONFLICT (symbol) DO UPDATE SET domain = EXCLUDED.domain, feed_url = EXCLUDED.feed_url, kind = EXCLUDED.kind, items = EXCLUDED.items,
                    probed = EXCLUDED.probed, discovered_at = EXCLUDED.discovered_at, last_ok_at = COALESCE(EXCLUDED.last_ok_at, ir_feeds.last_ok_at)"""),
                {"s": sym, "d": d, "u": url, "k": kind, "i": items, "p": probes, "now": now, "ok": now if url else None})
        await s.commit()
    with_domain = sum(1 for v in results.values() if v[0])
    with_feed = sum(1 for v in results.values() if v[1])
    summary = {"probed_tickers": len(results), "with_domain": with_domain, "with_feed": with_feed, "feeds_by_kind": {k: sum(1 for v in results.values() if v[2] == k) for k in ("rss", "atom")},
               "requests": sum(v[4] for v in results.values()), "error": None}
    print(f"  domains {with_domain}/{len(results)}, feeds found {with_feed}/{len(results)}; {summary['requests']} probe request(s)")
    await record_step_fields(STEP_LABEL, summary)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
