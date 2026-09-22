"""Seed analyst upgrades/downgrades from yfinance into the events table.

Fetches .upgrades_downgrades for each active ticker and upserts into events
with event_type=ANALYST_ACTION.  Metadata stores firm, action, grades, and
price targets.

yfinance reliably provides ~10+ years of history (back to ~2012 for large-caps).
The full depth is ingested on first run; subsequent runs skip existing rows.

Resumable skip logic: tickers whose last analyst action event was updated
within SKIP_WITHIN_DAYS are skipped.  This gives natural resume behaviour —
if a run is killed at ticker N, the next night picks up where it left off.

CLI
---
    python -m app.scripts.seed_analyst_actions
    python -m app.scripts.seed_analyst_actions --limit 5
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import func, select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.system_metadata_service import get_value, set_value

BATCH_SIZE = 5
BATCH_SLEEP = 2.0
RETRY_DELAYS = (5,)         # one retry; a slow provider must not cost 3 x FETCH_TIMEOUT per ticker
FETCH_TIMEOUT = 30          # per-ticker yfinance timeout (seconds)
SKIP_WITHIN_DAYS = 14       # skip tickers refreshed within this window
TIME_BUDGET_SECONDS = 1000  # stop cleanly before the refresh runner's 1200 s kill, keeping progress
ATTEMPTED_KEY = "analyst_actions_attempted"   # system_metadata: {symbol: iso_date}, survives deploys

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
    Raises on hard failure so the retry wrapper can catch it.
    """
    ticker = yf.Ticker(symbol)
    df = ticker.upgrades_downgrades

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


# ── Skip logic ──────────────────────────────────────────────────────────────

async def _load_attempted() -> dict[str, str]:
    """{symbol: iso_date} of tickers already attempted, from system_metadata."""
    async with AsyncSessionLocal() as session:
        raw = await get_value(session, ATTEMPTED_KEY)
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


async def _save_attempted(data: dict[str, str]) -> None:
    """Checkpoint: called after every batch so a killed run keeps what it did."""
    async with AsyncSessionLocal() as session:
        await set_value(session, ATTEMPTED_KEY, json.dumps(data))
        await session.commit()


def _build_skip_set(attempted: dict[str, str]) -> set[str]:
    """Return symbols attempted within SKIP_WITHIN_DAYS."""
    cutoff = (date.today() - timedelta(days=SKIP_WITHIN_DAYS)).isoformat()
    return {sym for sym, d in attempted.items() if d >= cutoff}


# ── Per-ticker bulk processing ───────────────────────────────────────────────

async def _process_ticker(ticker: Ticker, loop) -> tuple[str, int, str | None]:
    """Fetch + upsert one ticker. Returns (outcome, inserted, detail).

    outcome: "ok" (rows upserted), "empty" (provider has nothing for this
    symbol, e.g. a 404), or "failed" (timeout or error after the retry).
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0,) + RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            actions = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch_analyst_actions_sync, ticker.symbol),
                timeout=FETCH_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            continue
        if not actions:
            return "empty", 0, None
        inserted = 0
        async with AsyncSessionLocal() as session:
            for row in actions:
                if await _upsert_analyst_event(session, ticker, row):
                    inserted += 1
            await session.commit()
        return "ok", inserted, None

    detail = "timeout" if isinstance(last_exc, asyncio.TimeoutError) else f"{type(last_exc).__name__}: {str(last_exc)[:120]}"
    return "failed", 0, detail


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    ROTATION_LIMIT = 120

    async with AsyncSessionLocal() as session:
        # Subquery: latest analyst action event_date per ticker
        latest_action = (
            select(
                Event.ticker_id,
                func.max(Event.event_date).label("max_date"),
            )
            .where(Event.event_type == EventType.ANALYST_ACTION)
            .group_by(Event.ticker_id)
            .subquery()
        )

        candidates: list[Ticker] = list(
            (await session.execute(
                select(Ticker)
                .outerjoin(latest_action, Ticker.id == latest_action.c.ticker_id)
                .where(Ticker.is_active.is_(True))
                .order_by(latest_action.c.max_date.asc().nulls_first())
                .limit(ROTATION_LIMIT)
            )).scalars().all()
        )

    # Skip tickers attempted within SKIP_WITHIN_DAYS (checkpointed in system_metadata)
    attempted = await _load_attempted()
    skip_set = _build_skip_set(attempted)
    to_process = [t for t in candidates if t.symbol not in skip_set]
    n_skipped = len(candidates) - len(to_process)
    if n_skipped:
        print(f"{n_skipped} skipped (attempted within {SKIP_WITHIN_DAYS} days).", flush=True)

    print(f"Processing {len(to_process)} tickers (oldest-first rotation), budget {TIME_BUDGET_SECONDS}s.", flush=True)

    if not to_process:
        print("Nothing to process.")
        return 0

    loop = asyncio.get_event_loop()
    started = time.monotonic()
    succeeded = 0
    empty_list: list[str] = []
    inserted_total = 0
    failed_list: list[str] = []
    today_iso = date.today().isoformat()
    prune_cutoff = (date.today() - timedelta(days=SKIP_WITHIN_DAYS * 2)).isoformat()

    batches = [to_process[i:i + BATCH_SIZE] for i in range(0, len(to_process), BATCH_SIZE)]
    stopped_early = False

    for batch_idx, batch in enumerate(batches):
        results = await asyncio.gather(*(_process_ticker(t, loop) for t in batch))
        for ticker, (outcome, inserted, detail) in zip(batch, results):
            # Every outcome counts as attempted: a failing ticker must not block the rotation night after night.
            attempted[ticker.symbol] = today_iso
            if outcome == "ok":
                succeeded += 1
                inserted_total += inserted
            elif outcome == "empty":
                succeeded += 1
                empty_list.append(ticker.symbol)
            else:
                failed_list.append(ticker.symbol)
                print(f"  ✗ {ticker.symbol}: {detail}", flush=True)

        # Checkpoint after every batch so a kill keeps this batch's work.
        attempted = {sym: d for sym, d in attempted.items() if d >= prune_cutoff}
        await _save_attempted(attempted)
        print(
            f"  batch {batch_idx + 1}/{len(batches)}  ok={succeeded} new={inserted_total} "
            f"empty={len(empty_list)} fail={len(failed_list)}  {time.monotonic() - started:.0f}s",
            flush=True,
        )

        elapsed = time.monotonic() - started
        if batch_idx < len(batches) - 1 and elapsed > TIME_BUDGET_SECONDS:
            stopped_early = True
            left = len(to_process) - (batch_idx + 1) * BATCH_SIZE
            print(f"  Time budget reached after {elapsed:.0f}s; {left} tickers left for the next run.", flush=True)
            break
        if batch_idx < len(batches) - 1:
            await asyncio.sleep(BATCH_SLEEP)

    print()
    print(f"{'─' * 60}")
    print(f"  ✓ {succeeded} tickers processed  📊 {inserted_total} analyst actions inserted  "
          f"○ {len(empty_list)} with nothing from the provider  ✗ {len(failed_list)} failed"
          + ("  (stopped at time budget)" if stopped_early else ""))
    if empty_list:
        print(f"\n  Nothing from provider (404/empty): {', '.join(empty_list)}")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 60}")
    # Partial progress is checkpointed, so a slow night is not a failed step;
    # exit 1 only when every ticker attempted failed.
    return 1 if failed_list and not succeeded else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
