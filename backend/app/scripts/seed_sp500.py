"""Bulk-ingest S&P 500 tickers from Wikipedia + yfinance.

Sources
-------
Ticker list : https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
              Cached locally at cache/sp500_list.json — scrape only when stale.
Market data : yfinance (market_cap, industry, exchange)

Behaviour
---------
- Skips tickers already in the DB with a non-null market_cap updated within 7 days.
- Processes in batches of 10 with 2 s sleep between batches.
- Retries each failure up to 3 times (2 s → 5 s → 12 s backoff).
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

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker


# ── Paths ─────────────────────────────────────────────────────────────────────

CACHE_DIR        = Path(__file__).parent / "cache"
SP500_CACHE      = CACHE_DIR / "sp500_list.json"
FAILED_CACHE     = CACHE_DIR / "failed_tickers.json"
CACHE_MAX_AGE_H  = 24          # re-scrape Wikipedia after this many hours

# ── Tuning ────────────────────────────────────────────────────────────────────

BATCH_SIZE       = 10
BATCH_SLEEP      = 2.0          # seconds between batches
RETRY_DELAYS     = (2, 5, 12)   # seconds for retry 1, 2, 3
SKIP_IF_UPDATED_WITHIN = 7      # days — skip recently-refreshed tickers

# ── Sector normalisation ──────────────────────────────────────────────────────

# Map non-canonical / yfinance labels → official GICS sector names.
# Canonical list: Communication Services, Consumer Discretionary,
# Consumer Staples, Energy, Financials, Health Care, Industrials,
# Information Technology, Materials, Real Estate, Utilities
SECTOR_NORM: dict[str, str] = {
    # yfinance labels
    "Financial Services":  "Financials",
    "Technology":          "Information Technology",
    "Healthcare":          "Health Care",
    "Consumer Cyclical":   "Consumer Discretionary",
    "Consumer Defensive":  "Consumer Staples",
    "Basic Materials":     "Materials",
    "Communication":       "Communication Services",
}


def normalize_sector(s: str | None) -> str | None:
    if not s:
        return s
    return SECTOR_NORM.get(s.strip(), s.strip())


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
        symbol = col(cells, "Symbol").replace(".", "-")   # BRK.B → BRK-B for yfinance
        if not symbol:
            continue
        rows.append({
            "symbol":   symbol,
            "name":     col(cells, "Security"),
            # Wikipedia renders "GICS Sector" without a space in get_text
            "sector":   col(cells, "GICSSector", "GICS Sector"),
            "industry": col(cells, "GICS Sub-Industry"),
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
    """Return symbols already in DB with a market_cap updated within SKIP_IF_UPDATED_WITHIN days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SKIP_IF_UPDATED_WITHIN)
    rows = (await session.execute(
        select(Ticker.symbol)
        .where(
            Ticker.is_active.is_(True),
            Ticker.market_cap.is_not(None),
            Ticker.updated_at >= cutoff,
        )
    )).scalars().all()
    return set(rows)


# ── yfinance fetch (sync, called in executor) ─────────────────────────────────

def _next_earnings_date(t: yf.Ticker) -> date | None:
    """Return the next upcoming earnings date from calendar or earnings_dates DataFrame."""
    today = date.today()
    # Primary: calendar dict
    try:
        cal = t.calendar
        if cal and isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            vals = raw if isinstance(raw, list) else ([raw] if raw is not None else [])
            for v in vals:
                d: date | None = None
                if isinstance(v, date):
                    d = v
                elif hasattr(v, "date"):
                    d = v.date()
                elif isinstance(v, str):
                    try:
                        d = date.fromisoformat(v[:10])
                    except ValueError:
                        pass
                if d and d >= today:
                    return d
    except Exception:
        pass
    # Fallback: first future row in earnings_dates DataFrame
    try:
        df = t.earnings_dates
        if df is not None and not df.empty:
            future = df[df.index.normalize() >= pd.Timestamp(today, tz="UTC")]
            if not future.empty:
                return future.index.min().date()
    except Exception:
        pass
    return None


def _fetch_yf(wiki_row: dict) -> dict:
    """Fetch live data from yfinance and merge with wiki metadata."""
    symbol = wiki_row["symbol"]
    t = yf.Ticker(symbol)
    info = t.info or {}
    # Wikipedia/GICS is authoritative; yfinance is fallback only
    sector   = wiki_row["sector"]   or info.get("sector")   or None
    industry = wiki_row["industry"] or info.get("industry") or None
    return {
        "symbol":        symbol,
        "name":          info.get("longName") or info.get("shortName") or wiki_row["name"] or None,
        "sector":        normalize_sector(sector),
        "industry":      industry,
        "exchange":      info.get("exchange") or None,
        "market_cap":    info.get("marketCap") or None,
        "next_earnings": _next_earnings_date(t),
    }


# ── DB upserts ────────────────────────────────────────────────────────────────

async def upsert_ticker(session, data: dict) -> Ticker:
    stmt = (
        pg_insert(Ticker)
        .values(
            symbol       = data["symbol"],
            name         = data["name"],
            sector       = data["sector"],
            industry     = data["industry"],
            exchange     = data["exchange"],
            market_cap   = data["market_cap"],
            is_active    = True,
            index_member = True,
        )
        .on_conflict_do_update(
            index_elements=["symbol"],
            set_=dict(
                name         = data["name"],
                sector       = data["sector"],
                industry     = data["industry"],
                exchange     = data["exchange"],
                market_cap   = data["market_cap"],
                index_member = True,
                updated_at   = datetime.now(timezone.utc),
            ),
        )
        .returning(Ticker)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def upsert_earnings_event(session, ticker: Ticker, earnings_date: date) -> bool:
    """Upsert an earnings event. Returns True if a new row was created."""
    existing = await session.scalar(
        select(Event).where(
            Event.ticker_id  == ticker.id,
            Event.event_date == earnings_date,
            Event.event_type == EventType.EARNINGS,
        )
    )
    if existing:
        existing.title  = f"{ticker.symbol} Earnings"
        existing.source = DataSource.YFINANCE
        return False

    session.add(Event(
        ticker_id  = ticker.id,
        event_type = EventType.EARNINGS,
        event_date = earnings_date,
        title      = f"{ticker.symbol} Earnings",
        source     = DataSource.YFINANCE,
        is_confirmed = False,
        metadata_  = {},
    ))
    return True


# ── Per-ticker processing with retries ────────────────────────────────────────

# Returns (ticker_ok, event_created_or_updated, had_earnings_date)
TickerResult = tuple[bool, bool, bool]


async def process_ticker(wiki_row: dict, loop) -> TickerResult:
    """Fetch + upsert ticker and optional earnings event. Returns (ok, event_touched, had_date)."""
    symbol = wiki_row["symbol"]
    last_exc: Exception | None = None

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            data = await loop.run_in_executor(None, _fetch_yf, wiki_row)
            async with AsyncSessionLocal() as session:
                ticker = await upsert_ticker(session, data)

                event_touched = False
                had_date      = False
                if data["next_earnings"] is not None:
                    had_date      = True
                    event_touched = await upsert_earnings_event(session, ticker, data["next_earnings"])

                await session.commit()

            if not had_date:
                tqdm.write(f"  ⚠  {symbol}: no upcoming earnings date")
            return True, event_touched, had_date
        except Exception as exc:
            last_exc = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)

    tqdm.write(f"  ✗ {symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, False, False


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(retry_only: bool, limit: int | None, force_update: bool = False) -> int:
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

    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 2. Skip recently-updated tickers (unless --force-update)
    async with AsyncSessionLocal() as session:
        skip_set = set() if force_update else await build_skip_set(session)

    to_process = [r for r in candidates if r["symbol"] not in skip_set]
    skipped    = len(candidates) - len(to_process)
    if skipped:
        print(f"{skipped} skipped (recently updated, market_cap present).", flush=True)

    if not to_process:
        print("Nothing to process.")
        return 0

    # 3. Process in batches
    loop = asyncio.get_event_loop()
    succeeded:      list[str] = []
    failed:         list[str] = []
    events_touched: int = 0
    no_earnings:    int = 0

    batches = [to_process[i : i + BATCH_SIZE] for i in range(0, len(to_process), BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [process_ticker(row, loop) for row in batch]
            results = await asyncio.gather(*tasks)

            for row, (ok, event_touched, had_date) in zip(batch, results):
                sym = row["symbol"]
                if ok:
                    succeeded.append(sym)
                    if event_touched:
                        events_touched += 1
                    if not had_date:
                        no_earnings += 1
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
    print(f"  📅 {events_touched} earnings events created/updated  "
          f"({no_earnings} tickers had no upcoming earnings date)")
    if failed:
        print(f"\n  Failed symbols: {', '.join(failed)}")
        print("  Run `make seed-sp500-retry` to retry just those.")
    print(f"{'─' * 50}")

    return 1 if failed else 0


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
