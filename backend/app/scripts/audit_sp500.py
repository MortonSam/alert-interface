"""Deep data audit for the 503-ticker S&P 500 dataset.

Read-only — no writes. Prints a structured report and exits 0 always
(this is an audit, not a gate). Run after seed_sp500.py to spot data
quality issues before deciding what to fix.

Usage
-----
    python -m app.scripts.audit_sp500
    docker compose exec backend python -m app.scripts.audit_sp500
"""

from __future__ import annotations

import asyncio
import random
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import func, select, text

from app.database import AsyncSessionLocal
from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker


# ── Formatting helpers ────────────────────────────────────────────────────────

def header(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def subheader(title: str) -> None:
    print(f"\n  ── {title}")


def row(label: str, value: object, flag: str = "") -> None:
    flag_str = f"  {flag}" if flag else ""
    print(f"    {label:<42} {value}{flag_str}")


def fmt_cap(n: int | None) -> str:
    if n is None:
        return "null"
    if n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if n >= 1e9:
        return f"${n / 1e9:.1f}B"
    if n >= 1e6:
        return f"${n / 1e6:.0f}M"
    return f"${n:,}"


# ── Database audit sections ───────────────────────────────────────────────────

async def audit_sectors(session) -> None:
    header("TICKER CHECKS — SECTOR DISTRIBUTION")

    rows = (await session.execute(
        select(Ticker.sector, func.count(Ticker.id).label("n"))
        .group_by(Ticker.sector)
        .order_by(func.count(Ticker.id).desc())
    )).all()

    total = sum(r.n for r in rows)
    print(f"\n    {'Sector':<40} {'Count':>6}  {'%':>5}")
    print(f"    {'─' * 40}  {'─' * 6}  {'─' * 5}")
    flags = []
    for r in rows:
        sector = r.sector or "(null)"
        pct = r.n / total * 100
        flag = ""
        if r.n < 5:
            flag = "⚠ <5 tickers"
            flags.append(f"{sector}: {r.n}")
        elif r.n > 100:
            flag = "⚠ >100 tickers"
            flags.append(f"{sector}: {r.n}")
        print(f"    {sector:<40} {r.n:>6}   {pct:>4.1f}%  {flag}")

    if not flags:
        print("\n    ✓ All sectors in expected range (5–100 tickers)")
    else:
        print(f"\n    ⚠ Flagged: {', '.join(flags)}")


async def audit_market_cap_extremes(session) -> None:
    header("TICKER CHECKS — MARKET CAP SANITY")

    subheader("Top 10 by market_cap")
    top = (await session.execute(
        select(Ticker.symbol, Ticker.name, Ticker.market_cap)
        .where(Ticker.market_cap.is_not(None))
        .order_by(Ticker.market_cap.desc())
        .limit(10)
    )).all()
    for r in top:
        print(f"    {r.symbol:<8} {fmt_cap(r.market_cap):>10}  {(r.name or '')[:40]}")

    subheader("Bottom 10 by market_cap")
    bottom = (await session.execute(
        select(Ticker.symbol, Ticker.name, Ticker.market_cap)
        .where(Ticker.market_cap.is_not(None))
        .order_by(Ticker.market_cap.asc())
        .limit(10)
    )).all()
    for r in bottom:
        print(f"    {r.symbol:<8} {fmt_cap(r.market_cap):>10}  {(r.name or '')[:40]}")

    subheader("Tickers with market_cap < $1B  (S&P 500 min is ~$15B)")
    small = (await session.execute(
        select(Ticker.symbol, Ticker.name, Ticker.market_cap)
        .where(Ticker.market_cap < 1_000_000_000)
        .order_by(Ticker.market_cap.asc())
    )).all()
    if small:
        for r in small:
            print(f"    ⚠ {r.symbol:<8} {fmt_cap(r.market_cap):>10}  {(r.name or '')[:40]}")
    else:
        print("    ✓ No tickers below $1B")

    subheader("Tickers with market_cap < $15B  (below S&P 500 minimum)")
    borderline = (await session.execute(
        select(Ticker.symbol, Ticker.name, Ticker.market_cap)
        .where(Ticker.market_cap < 15_000_000_000)
        .order_by(Ticker.market_cap.asc())
        .limit(20)
    )).all()
    total_under15 = await session.scalar(
        select(func.count(Ticker.id)).where(Ticker.market_cap < 15_000_000_000)
    )
    print(f"    {total_under15} tickers under $15B (showing first 20):")
    for r in borderline:
        print(f"      {r.symbol:<8} {fmt_cap(r.market_cap):>10}  {(r.name or '')[:40]}")


async def audit_name_quality(session) -> None:
    header("TICKER CHECKS — NAME QUALITY")

    all_tickers = (await session.execute(
        select(Ticker.symbol, Ticker.name)
    )).all()

    short_names  = [(r.symbol, r.name) for r in all_tickers
                    if r.name and len(r.name) < 5]
    all_caps     = [(r.symbol, r.name) for r in all_tickers
                    if r.name and r.name == r.name.upper() and len(r.name) > 4]
    error_names  = [(r.symbol, r.name) for r in all_tickers
                    if r.name and any(x in r.name for x in ("Error", "error", "N/A", "None", "null"))]
    null_names   = [(r.symbol, r.name) for r in all_tickers if not r.name]

    subheader(f"Short names (< 5 chars): {len(short_names)}")
    for sym, name in short_names:
        print(f"    ⚠ {sym:<8} {name!r}")
    if not short_names:
        print("    ✓ None")

    subheader(f"ALL-CAPS names (possible ticker echoes): {len(all_caps)}")
    for sym, name in all_caps[:15]:
        print(f"    ⚠ {sym:<8} {name!r}")
    if len(all_caps) > 15:
        print(f"    ... and {len(all_caps) - 15} more")
    if not all_caps:
        print("    ✓ None")

    subheader(f"Error-string names: {len(error_names)}")
    for sym, name in error_names:
        print(f"    ⚠ {sym:<8} {name!r}")
    if not error_names:
        print("    ✓ None")

    subheader(f"Null/empty names: {len(null_names)}")
    for sym, name in null_names:
        print(f"    ⚠ {sym}")
    if not null_names:
        print("    ✓ None")


async def audit_exchanges(session) -> None:
    header("TICKER CHECKS — EXCHANGE DISTRIBUTION")

    EXPECTED = {"NMS", "NYQ", "NGS", "ASE", "BTS", "PCX", "NCM"}

    rows = (await session.execute(
        select(Ticker.exchange, func.count(Ticker.id).label("n"))
        .group_by(Ticker.exchange)
        .order_by(func.count(Ticker.id).desc())
    )).all()

    print(f"\n    {'Exchange':<12} {'Count':>6}  Status")
    print(f"    {'─' * 12}  {'─' * 6}  {'─' * 20}")
    unexpected = []
    for r in rows:
        exch = r.exchange or "(null)"
        status = "✓ expected" if exch in EXPECTED else "⚠ unexpected"
        if exch not in EXPECTED:
            unexpected.append(f"{exch} ({r.n})")
        print(f"    {exch:<12} {r.n:>6}  {status}")

    if unexpected:
        print(f"\n    ⚠ Unexpected exchanges: {', '.join(unexpected)}")
    else:
        print("\n    ✓ All exchanges are from the expected set")


async def audit_events_past(session) -> None:
    header("EVENT CHECKS — PAST EARNINGS DATES")

    today = date.today()
    rows = (await session.execute(
        select(Ticker.symbol, Event.event_date)
        .join(Ticker, Ticker.id == Event.ticker_id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date < today,
        )
        .order_by(Event.event_date.desc())
    )).all()

    if rows:
        print(f"\n    ⚠ {len(rows)} earnings event(s) with event_date in the past:")
        for r in rows[:20]:
            print(f"      {r.symbol:<8} {r.event_date}")
        if len(rows) > 20:
            print(f"      ... and {len(rows) - 20} more")
    else:
        print("\n    ✓ No past-dated earnings events")


async def audit_events_far_future(session) -> None:
    header("EVENT CHECKS — FAR-FUTURE EARNINGS (> 120 DAYS)")

    cutoff = date.today() + timedelta(days=120)
    rows = (await session.execute(
        select(Ticker.symbol, Event.event_date)
        .join(Ticker, Ticker.id == Event.ticker_id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date > cutoff,
        )
        .order_by(Event.event_date.desc())
    )).all()

    if rows:
        print(f"\n    ⚠ {len(rows)} earnings event(s) scheduled > 120 days out (possibly stale Q+1 estimates):")
        for r in rows[:20]:
            days_out = (r.event_date - date.today()).days
            print(f"      {r.symbol:<8} {r.event_date}  ({days_out} days)")
        if len(rows) > 20:
            print(f"      ... and {len(rows) - 20} more")
    else:
        print("\n    ✓ No earnings events beyond 120 days")


async def audit_events_monthly_distribution(session) -> None:
    header("EVENT CHECKS — MONTHLY EARNINGS DISTRIBUTION")

    rows = (await session.execute(
        select(
            func.to_char(Event.event_date, "YYYY-MM").label("ym"),
            func.count(Event.id).label("n"),
        )
        .where(Event.event_type == EventType.EARNINGS)
        .group_by(text("ym"))
        .order_by(text("ym"))
    )).all()

    print(f"\n    {'Month':<10} {'Count':>6}  Bar")
    print(f"    {'─' * 10}  {'─' * 6}  {'─' * 30}")
    for r in rows:
        bar = "█" * r.n
        flag = " ⚠ very few" if r.n < 5 else (" ⚠ very many" if r.n > 150 else "")
        print(f"    {r.ym:<10} {r.n:>6}  {bar[:50]}{flag}")


async def audit_events_today(session) -> None:
    header("EVENT CHECKS — EARNINGS DATED TODAY")

    today = date.today()
    rows = (await session.execute(
        select(Ticker.symbol, Ticker.name, Event.event_date)
        .join(Ticker, Ticker.id == Event.ticker_id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date == today,
        )
        .order_by(Ticker.symbol)
    )).all()

    if rows:
        print(f"\n    {len(rows)} ticker(s) with earnings scheduled today ({today}):")
        for r in rows:
            print(f"      {r.symbol:<8} {(r.name or '')[:50]}")
        print("\n    (Verify these are actually reporting today before trusting the data.)")
    else:
        print(f"\n    ✓ No earnings events dated today ({today})")


# ── yfinance spot-check ───────────────────────────────────────────────────────

async def audit_spot_check(session) -> None:
    header("SPOT-CHECK — 5 RANDOM TICKERS vs YFINANCE LIVE")

    # Pick 5 random tickers that have a market_cap so we have something to compare
    all_syms = (await session.execute(
        select(Ticker.symbol, Ticker.name, Ticker.sector, Ticker.market_cap, Ticker.exchange)
        .where(Ticker.market_cap.is_not(None))
        .order_by(func.random())
        .limit(5)
    )).all()

    print()
    FIELDS = ["name", "sector", "market_cap", "exchange"]

    for db_row in all_syms:
        sym = db_row.symbol
        print(f"  ── {sym} {'─' * (50 - len(sym))}")
        try:
            info = yf.Ticker(sym).info or {}
        except Exception as exc:
            print(f"    ✗ yfinance fetch failed: {exc}")
            continue

        yf_data = {
            "name":       info.get("longName") or info.get("shortName"),
            "sector":     info.get("sector"),
            "market_cap": info.get("marketCap"),
            "exchange":   info.get("exchange"),
        }
        db_data = {
            "name":       db_row.name,
            "sector":     db_row.sector,
            "market_cap": db_row.market_cap,
            "exchange":   db_row.exchange,
        }

        any_drift = False
        for field in FIELDS:
            db_val = db_data[field]
            yf_val = yf_data[field]

            if field == "market_cap" and db_val and yf_val:
                drift_pct = abs(db_val - yf_val) / max(abs(yf_val), 1) * 100
                status = "✓" if drift_pct < 5 else "⚠ drift"
                flag   = f"  ({drift_pct:.1f}% drift)" if drift_pct >= 5 else ""
                any_drift = any_drift or drift_pct >= 5
                print(f"    {field:<14} DB={fmt_cap(db_val):<12} YF={fmt_cap(yf_val):<12} {status}{flag}")
            else:
                match = db_val == yf_val
                status = "✓" if match else "⚠ mismatch"
                any_drift = any_drift or not match
                db_str = str(db_val)[:30] if db_val else "(null)"
                yf_str = str(yf_val)[:30] if yf_val else "(null)"
                print(f"    {field:<14} DB={db_str:<32} YF={yf_str:<32} {status}")

        if not any_drift:
            print("    ✓ All fields match (within 5% for market_cap)")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n" + "█" * 60)
    print("  S&P 500 DATA AUDIT")
    print(f"  Run date: {date.today()}")
    print("█" * 60)

    async with AsyncSessionLocal() as session:
        total_tickers = await session.scalar(select(func.count(Ticker.id)))
        total_events  = await session.scalar(
            select(func.count(Event.id)).where(Event.event_type == EventType.EARNINGS)
        )
        print(f"\n  Dataset: {total_tickers} tickers, {total_events} earnings events")

        await audit_sectors(session)
        await audit_market_cap_extremes(session)
        await audit_name_quality(session)
        await audit_exchanges(session)
        await audit_events_past(session)
        await audit_events_far_future(session)
        await audit_events_monthly_distribution(session)
        await audit_events_today(session)
        await audit_spot_check(session)

    print("\n" + "█" * 60)
    print("  AUDIT COMPLETE — review flagged items above")
    print("█" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
