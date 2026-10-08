"""Bulk-ingest S&P 500 constituent membership from Wikipedia.

Sources
-------
Ticker list : https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
              Cached locally at cache/sp500_list.json — scrape only when stale.

This script handles constituent membership, sector, and industry only.
Market cap and name are filled by refresh_profiles (Finnhub).
Earnings calendar is filled by refresh_earnings_calendar (Finnhub).

Behaviour
---------
- Inserts new tickers with sector/industry from Wikipedia GICS.
- Updates sector/industry and index_member for existing tickers.
- Does NOT overwrite name, market_cap, or exchange (managed by Finnhub).
- Skips tickers already updated within 7 days.
- Persists failed symbols to cache/failed_tickers.json for later retry.

CLI flags
---------
  --retry-only    Only attempt symbols listed in failed_tickers.json
  --limit N       Cap the candidate list at N (useful for testing)

Usage
-----
    python -m app.scripts.seed_sp500
    python -m app.scripts.seed_sp500 --limit 20
    python -m app.scripts.seed_sp500 --retry-only
    make seed-sp500
    make seed-sp500-retry
"""

from __future__ import annotations
from app.services.redact import redact

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.ticker import Ticker


# ── Paths ─────────────────────────────────────────────────────────────────────

CACHE_DIR        = Path(__file__).parent / "cache"
SP500_CACHE      = CACHE_DIR / "sp500_list.json"
FAILED_CACHE     = CACHE_DIR / "failed_tickers.json"
CACHE_MAX_AGE_H  = 24          # re-scrape Wikipedia after this many hours

# ── Tuning ────────────────────────────────────────────────────────────────────

BATCH_SIZE       = 10
BATCH_SLEEP      = 0.5          # seconds between batches (no yfinance, just DB)
SKIP_IF_UPDATED_WITHIN = 7      # days — skip recently-refreshed tickers


# ── Wikipedia scrape ──────────────────────────────────────────────────────────

def _scrape_sp500() -> list[dict]:
    """Fetch S&P 500 list from Wikipedia and return list of dicts."""
    print("Scraping Wikipedia S&P 500 list...", flush=True)
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", {"class": "wikitable"})
    if not table:
        raise RuntimeError("Could not find wikitable on S&P 500 Wikipedia page")

    all_rows = table.find_all("tr")
    if not all_rows:
        raise RuntimeError("S&P 500 wikitable has no rows")

    # Headers are <th> elements in the first row (no <thead> wrapper)
    headers = [th.get_text(strip=True) for th in all_rows[0].find_all("th")]

    def col(cells, *names: str) -> str:
        """Return text of the first matching column name (tries each alias)."""
        for name in names:
            try:
                idx = headers.index(name)
                return cells[idx].get_text(strip=True)
            except (ValueError, IndexError):
                continue
        return ""

    rows = []
    for tr in all_rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        symbol = col(cells, "Symbol").replace(".", "-")   # BRK.B → BRK-B
        if not symbol:
            continue
        rows.append({
            "symbol":   symbol,
            "name":     col(cells, "Security"),
            # Wikipedia renders "GICS Sector" without a space in get_text
            "sector":   col(cells, "GICSSector", "GICS Sector"),
            "industry": col(cells, "GICS Sub-Industry"),
            "cik":      col(cells, "CIK"),
        })

    print(f"  Found {len(rows)} S&P 500 constituents.", flush=True)
    return rows


def load_sp500_list() -> list[dict]:
    """Return cached list, re-scraping if cache is missing or stale."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if SP500_CACHE.exists():
        age_h = (time.time() - SP500_CACHE.stat().st_mtime) / 3600
        if age_h < CACHE_MAX_AGE_H:
            data = json.loads(SP500_CACHE.read_text())
            print(f"Using cached S&P 500 list ({len(data)} tickers, {age_h:.1f}h old).", flush=True)
            return data

    data = _scrape_sp500()
    SP500_CACHE.write_text(json.dumps(data, indent=2))
    return data


# ── Failed-ticker cache ───────────────────────────────────────────────────────

def load_failed() -> list[str]:
    if not FAILED_CACHE.exists():
        return []
    return json.loads(FAILED_CACHE.read_text())


def save_failed(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_CACHE.write_text(json.dumps(sorted(symbols), indent=2))


# ── Recently-updated skip logic ───────────────────────────────────────────────

async def build_skip_set(session) -> set[str]:
    """Return symbols recently updated within SKIP_IF_UPDATED_WITHIN days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SKIP_IF_UPDATED_WITHIN)
    rows = (await session.execute(
        select(Ticker.symbol)
        .where(
            Ticker.is_active.is_(True),
            Ticker.updated_at >= cutoff,
        )
    )).scalars().all()
    return set(rows)


# ── DB upserts ────────────────────────────────────────────────────────────────

MIN_CONSTITUENTS = 480      # a scrape smaller than this is a broken page, not an index that shrank: nothing is deactivated from it
SP500_STEP_LABEL = "Ticker data (seed_sp500)"


async def deactivate_index_leavers(session, leavers: list[str], reasons: dict[str, str], today: date) -> dict[str, str]:
    """The confirmed leavers (services/index_membership.decide) become inactive (rows kept, hidden at read time) with the reason
    naming the night and what confirmed it. Returns {symbol: reason}."""
    from sqlalchemy import text as _text
    out: dict[str, str] = {}
    for sym in leavers:
        reason = f"left the S&P 500 on {today.isoformat()}: {reasons.get(sym, 'missing from the constituent list')}"
        hit = (await session.execute(_text("""
            UPDATE tickers SET is_active = false, index_member = false, inactive_reason = :why, inactive_since = :d
            WHERE is_active AND symbol = :s RETURNING symbol"""), {"s": sym, "why": reason, "d": today})).scalar()
        if hit:
            out[sym] = reason
    return out


async def apply_membership(candidates: list[dict]) -> tuple[list[dict], int]:
    """index_member and is_active follow the constituent list only where a second source agrees (SPY's holdings) or the list shows the
    change two nights running (services/index_membership). A row whose CIK EDGAR assigns to another stored ticker changes nothing and
    is an error. Returns (the rows the per-ticker upsert may write: tonight's members, never a pending joiner or a conflicting row;
    the error count). The outcome is recorded for /health and the digest."""
    from sqlalchemy import text as _text
    from app.services.index_membership import PENDING_KEY, cik_conflicts, decide, fetch_spy_holdings
    from app.services.edgar_client import EdgarClient
    from app.services.system_metadata_service import get_value, set_value
    today = date.today()
    async with AsyncSessionLocal() as session:
        active = set((await session.execute(_text("SELECT symbol FROM tickers WHERE is_active"))).scalars().all())
        stored = set((await session.execute(_text("SELECT symbol FROM tickers"))).scalars().all())
        pending = json.loads(await get_value(session, PENDING_KEY) or "{}")
    try:
        edgar = EdgarClient()
        owners = await edgar.cik_owners()
    except Exception as exc:
        owners = {}
        print(f"  [WARN] EDGAR ticker map unreadable, CIK check skipped: {redact(exc)}", flush=True)
    conflicts = cik_conflicts(candidates, owners, stored)
    rows = [r for r in candidates if r["symbol"] not in conflicts]
    # a conflicting row's own symbol, when it is an active ticker, counts as still listed: a garbled row removes nothing
    scraped = {r["symbol"] for r in rows} | (set(conflicts) & active)
    if len(scraped) < MIN_CONSTITUENTS:
        print(f"  constituent list has only {len(scraped)} names (floor {MIN_CONSTITUENTS}): membership left untouched", flush=True)
        return [r for r in rows if r["symbol"] in active], len(conflicts)
    spy, spy_note = await fetch_spy_holdings()
    d = decide(scraped, active, spy, pending, today)
    members = sorted((scraped & active) | set(d.join) | set(d.pending_leave))
    async with AsyncSessionLocal() as session:
        left = await mark_index_members(session, members)
        deactivated = await deactivate_index_leavers(session, d.leave, d.why, today)
        await set_value(session, PENDING_KEY, json.dumps({"leave": d.pending_leave, "join": d.pending_join}))
        await session.commit()
    print(f"  second source: {spy_note}", flush=True)
    for sym, why in conflicts.items():
        print(f"  ERROR {sym}: scraped row ignored, {why}", flush=True)
    for sym in d.join:
        print(f"  {sym}: joins; {d.why[sym]}", flush=True)
    for sym, why in deactivated.items():
        print(f"  {sym}: inactive; {why}", flush=True)
    for sym in list(d.pending_leave) + list(d.pending_join):
        print(f"  {sym}: pending; {d.why[sym]}", flush=True)
    try:
        from app.services.step_outcomes import record_step_fields
        await record_step_fields(SP500_STEP_LABEL, {
            "constituents": len(scraped), "second_source": spy_note, "index_member_cleared": left, "deactivated_index_leavers": deactivated,
            "joined": {s: d.why[s] for s in d.join}, "pending": {s: d.why[s] for s in list(d.pending_leave) + list(d.pending_join)},
            "cik_conflicts": conflicts,
        })
    except Exception as exc:
        print(f"  [WARN] could not record the membership outcome: {redact(exc)}")
    allowed = set(members)
    return [r for r in rows if r["symbol"] in allowed], len(conflicts)


async def mark_index_members(session, members: list[str]) -> list[str]:
    """Set index_member = (symbol in members) for every active ticker. Returns the symbols cleared this run."""
    from sqlalchemy import text as _text
    cleared = (await session.execute(_text(
        "UPDATE tickers SET index_member = (symbol = ANY(:m)) WHERE is_active AND index_member <> (symbol = ANY(:m)) RETURNING symbol, index_member"
    ), {"m": list(members)})).all()
    return sorted(sym for sym, member in cleared if not member)


async def upsert_ticker(session, data: dict) -> None:
    stmt = (
        pg_insert(Ticker)
        .values(
            symbol       = data["symbol"],
            name         = data["name"] or None,
            sector       = data["sector"] or None,
            industry     = data["industry"] or None,
            is_active    = True,
            index_member = True,
        )
        .on_conflict_do_update(
            index_elements=["symbol"],
            set_=dict(
                sector       = data["sector"] or None,
                industry     = data["industry"] or None,
                index_member = True,
                updated_at   = datetime.now(timezone.utc),
            ),
        )
    )
    await session.execute(stmt)


# ── Per-ticker processing ────────────────────────────────────────────────────

async def process_ticker(wiki_row: dict) -> bool:
    """Upsert ticker from Wikipedia data. Returns True on success."""
    symbol = wiki_row["symbol"]
    try:
        async with AsyncSessionLocal() as session:
            await upsert_ticker(session, wiki_row)
            await session.commit()
        return True
    except Exception as exc:
        tqdm.write(f"  ✗ {symbol}: {redact(exc)}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(retry_only: bool, limit: int | None, force_update: bool = False) -> int:
    membership_errors = 0
    # 1. Determine candidate list
    if retry_only:
        failed_symbols = load_failed()
        if not failed_symbols:
            print("No failed tickers in cache. Nothing to retry.")
            return 0
        sp500 = load_sp500_list()
        by_symbol = {r["symbol"]: r for r in sp500}
        candidates = [by_symbol.get(s, {"symbol": s, "name": None, "sector": None, "industry": None})
                      for s in failed_symbols]
        print(f"Retrying {len(candidates)} previously-failed tickers.", flush=True)
    else:
        candidates = load_sp500_list()
        if limit is None:
            candidates, membership_errors = await apply_membership(candidates)

    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 2. Skip recently-updated tickers (unless --force-update)
    async with AsyncSessionLocal() as session:
        skip_set = set() if force_update else await build_skip_set(session)

    to_process = [r for r in candidates if r["symbol"] not in skip_set]
    skipped    = len(candidates) - len(to_process)
    if skipped:
        print(f"{skipped} skipped (recently updated).", flush=True)

    if not to_process:
        print("Nothing to process.")
        return 1 if membership_errors else 0

    # 3. Process in batches
    succeeded: list[str] = []
    failed:    list[str] = []

    batches = [to_process[i : i + BATCH_SIZE] for i in range(0, len(to_process), BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [process_ticker(row) for row in batch]
            results = await asyncio.gather(*tasks)

            for row, ok in zip(batch, results):
                sym = row["symbol"]
                if ok:
                    succeeded.append(sym)
                else:
                    failed.append(sym)
                bar.update(1)

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)

    # 4. Persist failures
    if retry_only:
        still_failed = [s for s in load_failed() if s not in succeeded]
        save_failed(still_failed)
    else:
        existing_failed = load_failed()
        merged_failed   = sorted(set(existing_failed) | set(failed) - set(succeeded))
        save_failed(merged_failed)
    # 5. Summary
    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {len(succeeded)} succeeded  "
          f"⚠ {skipped} skipped  "
          f"✗ {len(failed)} failed")
    if failed:
        print(f"\n  Failed symbols: {', '.join(failed)}")
        print("  Run `make seed-sp500-retry` to retry just those.")
    print(f"{'─' * 50}")

    if len(failed) > 10:
        print(f"  Too many failures ({len(failed)} > 10) — marking step as failed.")
        return 1
    if membership_errors:
        print(f"  {membership_errors} scraped row(s) carried another ticker's CIK and were ignored — marking step as failed.")
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk-ingest S&P 500 tickers")
    p.add_argument("--retry-only", action="store_true",
                   help="Only retry symbols from cache/failed_tickers.json")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Process only the first N candidates (for testing)")
    p.add_argument("--force-update", action="store_true",
                   help="Skip the 7-day freshness check and reprocess all tickers")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(main(retry_only=args.retry_only, limit=args.limit, force_update=args.force_update)))
