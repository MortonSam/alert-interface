"""Seed analyst upgrades/downgrades from yfinance into the events table.

Fetches .upgrades_downgrades for each active ticker and upserts into events
with event_type=ANALYST_ACTION.  Metadata stores firm, action, grades, and
price targets.

yfinance reliably provides ~10+ years of history (back to ~2012 for large-caps).
The full depth is ingested on first run; subsequent runs skip existing rows.

CLI
---
    python -m app.scripts.seed_analyst_actions
    python -m app.scripts.seed_analyst_actions --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker

BATCH_SIZE = 5
BATCH_SLEEP = 2.0
RETRY_DELAYS = (3, 8, 15)

# ── Action label mapping ────────────────────────────────────────────────────

ACTION_LABELS = {
    "up":   "Upgrade",
    "down": "Downgrade",
    "main": "Maintain",
    "reit": "Reiterate",
    "init": "Initiate",
}


# ── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_analyst_actions_sync(symbol: str) -> list[dict]:
    """Fetch all analyst upgrades/downgrades from yfinance.

    Returns list of dicts with: action_date, firm, action, to_grade,
    from_grade, price_target, prior_price_target.
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.upgrades_downgrades
    except Exception:
        return []

    if df is None or df.empty:
        return []

    results = []
    for ts, row in df.iterrows():
        try:
            action_date = ts.date() if hasattr(ts, "date") else ts
        except Exception:
            continue

        firm = (row.get("Firm") or "").strip()
        if not firm:
            continue

        action_code = (row.get("Action") or "").strip()
        to_grade = (row.get("ToGrade") or "").strip()
        from_grade = (row.get("FromGrade") or "").strip()

        price_target = row.get("currentPriceTarget")
        prior_target = row.get("priorPriceTarget")

        # Clean NaN values
        if price_target is not None and (isinstance(price_target, float) and math.isnan(price_target)):
            price_target = None
        if prior_target is not None and (isinstance(prior_target, float) and math.isnan(prior_target)):
            prior_target = None
        # Convert to float for JSON serialization (numpy float64 → float)
        if price_target is not None:
            price_target = float(price_target) if price_target != 0 else None
        if prior_target is not None:
            prior_target = float(prior_target) if prior_target != 0 else None

        results.append({
            "action_date": action_date,
            "firm": firm,
            "action": action_code,
            "to_grade": to_grade or None,
            "from_grade": from_grade or None,
            "price_target": price_target,
            "prior_price_target": prior_target,
        })

    return results


# ── Title builder ────────────────────────────────────────────────────────────

def _build_title(symbol: str, row: dict) -> str:
    """Build a human-readable title for the event."""
    action_label = ACTION_LABELS.get(row["action"], row["action"].title())
    parts = [f"{row['firm']}: {action_label}"]
    if row["to_grade"]:
        parts.append(f"to {row['to_grade']}")
    if row["from_grade"] and row["from_grade"] != row["to_grade"]:
        parts.append(f"(from {row['from_grade']})")
    return " ".join(parts)


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_analyst_event(
    session,
    ticker: Ticker,
    row: dict,
) -> bool:
    """Insert analyst action if not already present. Dedupes on (ticker, date, type, firm).
    Returns True if inserted."""
    existing = await session.scalar(
        select(Event.id).where(
            Event.ticker_id == ticker.id,
            Event.event_date == row["action_date"],
            Event.event_type == EventType.ANALYST_ACTION,
            Event.metadata_["firm"].astext == row["firm"],
        )
    )
    if existing is not None:
        return False

    metadata = {
        "firm": row["firm"],
        "action": row["action"],
        "to_grade": row["to_grade"],
        "from_grade": row["from_grade"],
    }
    if row["price_target"] is not None:
        metadata["price_target"] = row["price_target"]
    if row["prior_price_target"] is not None:
        metadata["prior_price_target"] = row["prior_price_target"]

    event = Event(
        ticker_id=ticker.id,
        event_type=EventType.ANALYST_ACTION,
        event_date=row["action_date"],
        title=_build_title(ticker.symbol, row),
        source=DataSource.YFINANCE,
        is_confirmed=True,
        metadata_=metadata,
    )
    session.add(event)
    return True


# ── Per-ticker bulk processing ───────────────────────────────────────────────

async def _process_ticker(ticker: Ticker, loop) -> tuple[bool, int]:
    """Fetch + upsert all analyst actions with retries. Returns (ok, inserted_count)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            actions = await loop.run_in_executor(
                None, _fetch_analyst_actions_sync, ticker.symbol
            )
            if not actions:
                return True, 0

            inserted = 0
            async with AsyncSessionLocal() as session:
                for row in actions:
                    if await _upsert_analyst_event(session, ticker, row):
                        inserted += 1
                await session.commit()
            return True, inserted
        except Exception as exc:
            last_exc = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)

    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed analyst actions from yfinance")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap the candidate list at N (for testing)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )

    candidates = all_tickers
    if args.limit is not None:
        candidates = candidates[:args.limit]
        print(f"--limit {args.limit}: processing first {len(candidates)} tickers.", flush=True)

    if not candidates:
        print("No tickers in database.")
        return 0

    loop = asyncio.get_event_loop()
    succeeded = 0
    inserted_total = 0
    failed_list: list[str] = []

    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]

    with tqdm(total=len(candidates), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [_process_ticker(t, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, inserted) in zip(batch, results):
                if ok:
                    succeeded += 1
                    inserted_total += inserted
                else:
                    failed_list.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=succeeded, new=inserted_total, fail=len(failed_list))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)

    print()
    print(f"{'─' * 60}")
    print(f"  ✓ {succeeded} tickers processed  📊 {inserted_total} analyst actions inserted  ✗ {len(failed_list)} failed")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 60}")
    return 1 if failed_list else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
