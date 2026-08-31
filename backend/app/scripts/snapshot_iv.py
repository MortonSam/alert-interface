"""Snapshot today's ATM implied volatility and 20-day realized vol for all active tickers.

Run daily (via ``make refresh`` or standalone) to build iv_history for future IV Rank.
Upserts on (symbol, date) — safe to re-run multiple times per day.

IV source: ingested option chains in system_metadata (pushed by chain_courier).
If no ingested chain exists for a ticker, no iv_history row is written.
RV source: yfinance price history (reliable from any IP).

Usage
-----
    python -m app.scripts.snapshot_iv
    python -m app.scripts.snapshot_iv --symbol AAPL   # single ticker
    python -m app.scripts.snapshot_iv --backfill-cleanup  # NULL out corrupt historical IVs only

TODO: Once >= 3-6 months of iv_history has accrued, compute true IV Rank/Percentile
the same way as realized vol rank (trailing 252 readings, rank + percentile) and display
both side-by-side on the ticker page.  The spread between IV Rank and RV Rank
(implied vs actual movement cost) is itself a tradeable signal:
  - High IV Rank, Low RV Rank  -> options overpriced vs realised movement (sell vol)
  - Low IV Rank,  High RV Rank -> options cheap vs realised movement (buy vol)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from datetime import date, timedelta

import sqlalchemy as sa

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.ticker import Ticker
from app.services.yfinance_client import YFinanceClient

# Sanity band — reject ATM IV outside this range
_IV_MIN = 0.05
_IV_MAX = 4.0


def _last_trading_day(d: date | None = None) -> date:
    """Roll weekends back to Friday.  Mon-Fri pass through unchanged."""
    d = d or date.today()
    wd = d.weekday()  # 0=Mon … 6=Sun
    if wd == 5:       # Saturday → Friday
        return d - timedelta(days=1)
    if wd == 6:       # Sunday → Friday
        return d - timedelta(days=2)
    return d


def _get_current_price(symbol: str) -> float | None:
    """Current price from yfinance daily history (reliable from any IP)."""
    try:
        hist = YFinanceClient.get_price_history(symbol, period="2d")
        if hist is not None and not hist.empty:
            price = float(hist["Close"].iloc[-1])
            if math.isnan(price):
                return None
            return price
    except Exception:
        pass
    return None


async def _backfill_cleanup() -> None:
    """NULL out corrupt iv_history rows where atm_iv < _IV_MIN."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(sa.text("""
            WITH updated AS (
                UPDATE iv_history SET atm_iv = NULL
                WHERE atm_iv IS NOT NULL AND atm_iv < :iv_min
                RETURNING symbol
            )
            SELECT symbol, COUNT(*) as cnt
            FROM updated
            GROUP BY symbol
            ORDER BY cnt DESC
            LIMIT 10
        """), {"iv_min": _IV_MIN})
        rows = result.all()
        await session.commit()

    if rows:
        total = sum(r.cnt for r in rows)
        print(f"\nBackfill cleanup: NULLed {total} row(s) with atm_iv < {_IV_MIN}")
        for r in rows:
            print(f"  {r.symbol}: {r.cnt} row(s)")
    else:
        print("\nBackfill cleanup: no corrupt rows found")


async def _get_ingested_chain(
    session, symbol: str, today: date,
) -> tuple[dict | None, str | None]:
    """Load the best ingested chain for symbol from system_metadata.

    Picks the nearest expiration >= today + 7 days.
    Returns (parsed chain dict, chosen expiration) or (None, None).
    """
    min_exp = (today + timedelta(days=7)).isoformat()

    result = await session.execute(
        sa.text(
            "SELECT key, value FROM system_metadata"
            " WHERE key LIKE :pattern ORDER BY key"
        ),
        {"pattern": f"chain:{symbol}:%"},
    )
    rows = result.all()

    if not rows:
        return None, None

    candidates = []
    for row in rows:
        parts = row.key.split(":")
        if len(parts) >= 3:
            exp_str = parts[2]
            if exp_str >= min_exp:
                candidates.append((exp_str, row.value))

    # If nothing >= min_exp, use the farthest available
    if not candidates:
        parts = rows[-1].key.split(":")
        if len(parts) >= 3:
            candidates = [(parts[2], rows[-1].value)]

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0])
    exp_str, chain_json = candidates[0]

    try:
        return json.loads(chain_json), exp_str
    except (json.JSONDecodeError, TypeError):
        return None, None


def _compute_atm_iv(
    chain: dict, current_price: float,
) -> tuple[float | None, float | None]:
    """Compute ATM IV from a parsed chain dict. Returns (atm_iv, atm_strike)."""
    calls = chain.get("calls", [])
    puts = chain.get("puts", [])

    all_strikes = sorted(
        {c["strike"] for c in calls} | {p["strike"] for p in puts}
    )
    if not all_strikes:
        return None, None

    atm_strike = min(all_strikes, key=lambda s: abs(s - current_price))
    atm_call = next((c for c in calls if c["strike"] == atm_strike), None)
    atm_put = next((p for p in puts if p["strike"] == atm_strike), None)

    ivs = [
        c["impliedVolatility"]
        for c in [atm_call, atm_put]
        if c and c.get("impliedVolatility") is not None
    ]
    atm_iv = sum(ivs) / len(ivs) if ivs else None
    return atm_iv, atm_strike


async def _snapshot_one(symbol: str, today: date) -> dict:
    """Fetch ATM IV from ingested chain + 20d RV from yfinance and upsert into iv_history."""
    loop = asyncio.get_event_loop()

    # ── Check for ingested chain first ────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        chain, chosen_exp = await _get_ingested_chain(session, symbol, today)

    if chain is None:
        return {
            "symbol": symbol,
            "atm_iv": None, "realized_vol_20d": None,
            "current_price": None, "atm_strike": None,
            "skipped": "no ingested chain",
        }

    # ── RV + current price from yfinance (price history is reliable) ─────────
    rv_data, current_price = await asyncio.gather(
        loop.run_in_executor(None, YFinanceClient.get_realized_vol_data, symbol),
        loop.run_in_executor(None, _get_current_price, symbol),
    )
    realized_vol_20d: float | None = rv_data.get("current_rv")

    # ── Compute ATM IV ────────────────────────────────────────────────────────
    atm_iv: float | None = None
    atm_strike: float | None = None

    if current_price is not None:
        atm_iv, atm_strike = _compute_atm_iv(chain, current_price)

    # ── Sanity band ───────────────────────────────────────────────────────────
    if atm_iv is not None and (atm_iv < _IV_MIN or atm_iv > _IV_MAX):
        print(
            f"  {symbol:8s}  SANITY: atm_iv={atm_iv:.4f}"
            f" outside [{_IV_MIN}, {_IV_MAX}] — writing NULL"
        )
        atm_iv = None

    # ── Upsert ────────────────────────────────────────────────────────────────
    stmt = sa.text("""
        INSERT INTO iv_history
            (id, symbol, date, atm_iv, realized_vol_20d,
             atm_strike, current_price, created_at)
        VALUES
            (gen_random_uuid(), :symbol, :date,
             :atm_iv, :realized_vol_20d, :atm_strike, :current_price, now())
        ON CONFLICT (symbol, date) DO UPDATE SET
            atm_iv           = EXCLUDED.atm_iv,
            realized_vol_20d = EXCLUDED.realized_vol_20d,
            atm_strike       = EXCLUDED.atm_strike,
            current_price    = EXCLUDED.current_price
    """)

    async with AsyncSessionLocal() as session:
        await session.execute(stmt, {
            "symbol": symbol, "date": today,
            "atm_iv": atm_iv, "realized_vol_20d": realized_vol_20d,
            "atm_strike": atm_strike, "current_price": current_price,
        })
        await session.commit()

    return {
        "symbol": symbol,
        "atm_iv": atm_iv, "realized_vol_20d": realized_vol_20d,
        "current_price": current_price, "atm_strike": atm_strike,
        "chosen_exp": chosen_exp,
    }


async def main(only_symbol: str | None = None, backfill: bool = False) -> int:
    today = _last_trading_day()
    print(f"\nIV Snapshot — {today}")
    print("─" * 60)

    # Always run backfill cleanup
    await _backfill_cleanup()

    if backfill:
        return 0

    if only_symbol:
        symbols = [only_symbol.upper()]
    else:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                sa.select(Ticker.symbol)
                .where(Ticker.is_active.is_(True))
                .order_by(Ticker.symbol)
            )
            symbols = [row[0] for row in result.fetchall()]

    print(f"\nSnapshotting {len(symbols)} ticker(s)...\n")
    ok = skipped = err = 0

    for symbol in symbols:
        try:
            row = await _snapshot_one(symbol, today)
            if row.get("skipped"):
                print(f"  {symbol:8s}  — {row['skipped']}")
                skipped += 1
                continue
            iv_str = (
                f"{row['atm_iv'] * 100:.2f}%"
                if row["atm_iv"] is not None else "—"
            )
            rv_str = (
                f"{row['realized_vol_20d'] * 100:.2f}%"
                if row["realized_vol_20d"] is not None else "—"
            )
            px_str = (
                f"${row['current_price']:.2f}"
                if row["current_price"] is not None else "—"
            )
            sk_str = (
                f"${row['atm_strike']:.2f}"
                if row["atm_strike"] is not None else "—"
            )
            exp_str = row.get("chosen_exp", "—")
            print(
                f"  {symbol:8s}  price={px_str:10s}"
                f"  ATM_strike={sk_str:10s}  ATM_IV={iv_str:8s}"
                f"  RV-20d={rv_str:8s}  exp={exp_str}"
            )
            ok += 1
        except Exception as exc:
            print(f"  {symbol:8s}  ERROR: {exc}")
            err += 1

    print(f"\n  Done: {ok} OK, {skipped} skipped (no chain), {err} error(s).")
    if err > 10:
        print(f"  Too many errors ({err} > 10) — marking step as failed.")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Snapshot ATM IV + realized vol for tickers."
    )
    parser.add_argument(
        "--symbol", metavar="SYM", default=None,
        help="Snapshot a single ticker only (default: all active).",
    )
    parser.add_argument(
        "--backfill-cleanup", action="store_true",
        help="NULL out corrupt historical IVs and exit.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(
        only_symbol=args.symbol,
        backfill=args.backfill_cleanup,
    )))
