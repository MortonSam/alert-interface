"""Read-only data-quality validation script.

Runs a battery of checks against the database and prints a structured report.

Exit codes
----------
0  — no errors (warnings are OK)
1  — one or more error-level checks failed

Usage
-----
    python -m app.scripts.validate_data
    make validate
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text

from app.database import AsyncSessionLocal
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker


# ── Result types ──────────────────────────────────────────────────────────────

PASS    = "pass"
WARN    = "warn"
ERROR   = "error"

@dataclass
class CheckResult:
    name: str
    level: str          # PASS | WARN | ERROR
    message: str
    rows: list[str] = field(default_factory=list)


# ── Individual checks ─────────────────────────────────────────────────────────

async def check_ticker_missing_metadata(session) -> CheckResult:
    rows = (await session.execute(
        select(Ticker.symbol, Ticker.sector, Ticker.industry, Ticker.exchange)
        .where(
            (Ticker.sector.is_(None)) |
            (Ticker.industry.is_(None)) |
            (Ticker.exchange.is_(None))
        )
        .order_by(Ticker.symbol)
    )).all()

    if not rows:
        return CheckResult("ticker_missing_metadata", PASS, "All tickers have sector, industry, and exchange")

    details = [
        f"{r.symbol}  sector={'?' if r.sector is None else r.sector}  "
        f"industry={'?' if r.industry is None else r.industry}  "
        f"exchange={'?' if r.exchange is None else r.exchange}"
        for r in rows
    ]
    return CheckResult(
        "ticker_missing_metadata", WARN,
        f"{len(rows)} ticker(s) missing sector, industry, or exchange",
        details,
    )


async def check_ticker_market_cap(session) -> CheckResult:
    rows = (await session.execute(
        select(Ticker.symbol, Ticker.market_cap)
        .where((Ticker.market_cap.is_(None)) | (Ticker.market_cap == 0))
        .order_by(Ticker.symbol)
    )).all()

    if not rows:
        return CheckResult("ticker_market_cap", PASS, "All tickers have a non-zero market cap")

    details = [f"{r.symbol}  market_cap={r.market_cap!r}" for r in rows]
    return CheckResult(
        "ticker_market_cap", WARN,
        f"{len(rows)} ticker(s) with null or zero market_cap",
        details,
    )


async def check_ticker_duplicate_symbols(session) -> CheckResult:
    rows = (await session.execute(
        select(Ticker.symbol, func.count(Ticker.id).label("n"))
        .group_by(Ticker.symbol)
        .having(func.count(Ticker.id) > 1)
    )).all()

    if not rows:
        return CheckResult("ticker_duplicate_symbols", PASS, "No duplicate ticker symbols")

    details = [f"{r.symbol}  count={r.n}" for r in rows]
    return CheckResult(
        "ticker_duplicate_symbols", ERROR,
        f"{len(rows)} duplicate symbol(s) found — unique constraint may be broken",
        details,
    )


async def check_events_stale_past(session) -> CheckResult:
    cutoff = date.today() - timedelta(days=14)
    rows = (await session.execute(
        select(Event.id, Event.event_date, Event.title, Event.event_type)
        .where(Event.event_date < cutoff)
        .order_by(Event.event_date.desc())
        .limit(20)
    )).all()

    if not rows:
        return CheckResult("events_stale_past", PASS, "No stale past events (older than 14 days)")

    details = [f"{r.event_date}  [{r.event_type}]  {r.title[:60]}" for r in rows]
    total = (await session.scalar(
        select(func.count(Event.id)).where(Event.event_date < cutoff)
    ))
    return CheckResult(
        "events_stale_past", WARN,
        f"{total} event(s) with event_date older than 14 days (showing first 20)",
        details,
    )


async def check_events_null_title(session) -> CheckResult:
    rows = (await session.execute(
        select(Event.id, Event.event_date, Event.event_type)
        .where(Event.title.is_(None))
        .order_by(Event.event_date)
    )).all()

    if not rows:
        return CheckResult("events_null_title", PASS, "All events have a title")

    details = [f"{r.event_date}  [{r.event_type}]  id={r.id}" for r in rows]
    return CheckResult(
        "events_null_title", ERROR,
        f"{len(rows)} event(s) with null title",
        details,
    )


async def check_macro_events_with_ticker(session) -> CheckResult:
    global_types = [EventType.MACRO, EventType.FOMC]
    rows = (await session.execute(
        select(Event.id, Event.event_date, Event.title, Event.ticker_id, Event.event_type)
        .where(
            Event.event_type.in_(global_types),
            Event.ticker_id.is_not(None),
        )
        .order_by(Event.event_date)
    )).all()

    if not rows:
        return CheckResult("macro_events_with_ticker", PASS, "All macro/FOMC events have ticker_id = NULL")

    details = [f"{r.event_date}  [{r.event_type}]  {r.title[:50]}  ticker_id={r.ticker_id}" for r in rows]
    return CheckResult(
        "macro_events_with_ticker", WARN,
        f"{len(rows)} macro/FOMC event(s) unexpectedly linked to a ticker",
        details,
    )


async def check_ticker_events_null_ticker(session) -> CheckResult:
    ticker_types = [
        EventType.EARNINGS, EventType.FDA, EventType.EX_DIVIDEND, EventType.PRODUCT_LAUNCH,
    ]
    rows = (await session.execute(
        select(Event.id, Event.event_date, Event.title, Event.event_type)
        .where(
            Event.event_type.in_(ticker_types),
            Event.ticker_id.is_(None),
        )
        .order_by(Event.event_date)
    )).all()

    if not rows:
        return CheckResult("ticker_events_null_ticker", PASS, "All ticker-specific events have a ticker_id")

    details = [f"{r.event_date}  [{r.event_type}]  {r.title[:50]}" for r in rows]
    return CheckResult(
        "ticker_events_null_ticker", ERROR,
        f"{len(rows)} ticker-specific event(s) missing a ticker_id",
        details,
    )


async def check_reactions_3d_equals_5d(session) -> CheckResult:
    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_3d,
            HistoricalReaction.pct_change_5d,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.pct_change_3d.is_not(None),
            HistoricalReaction.pct_change_5d.is_not(None),
            HistoricalReaction.pct_change_3d == HistoricalReaction.pct_change_5d,
        )
        .order_by(Ticker.symbol, HistoricalReaction.event_date)
    )).all()

    if not rows:
        return CheckResult("reactions_3d_equals_5d", PASS, "No rows where pct_change_3d = pct_change_5d (rollforward bug absent)")

    details = [
        f"{r.symbol}  {r.event_date}  3d={r.pct_change_3d}  5d={r.pct_change_5d}"
        for r in rows
    ]
    # ≤ 50 matches at 5-year/503-ticker scale is coincidental price equality (stock
    # barely moved between T+3 and T+5 trading days).  A systematic rollforward bug
    # would produce hundreds of matches.  Escalate to ERROR only if widespread.
    level = ERROR if len(rows) > 50 else WARN
    return CheckResult(
        "reactions_3d_equals_5d", level,
        f"{len(rows)} row(s) with identical pct_change_3d and pct_change_5d"
        + (" (likely coincidental price equality — verify no systematic pattern)" if level == WARN
           else " (rollforward bug — systematic pattern detected)"),
        details,
    )


async def check_reactions_1d_equals_3d(session) -> CheckResult:
    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.pct_change_3d,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.pct_change_1d.is_not(None),
            HistoricalReaction.pct_change_3d.is_not(None),
            HistoricalReaction.pct_change_1d == HistoricalReaction.pct_change_3d,
        )
        .order_by(Ticker.symbol, HistoricalReaction.event_date)
    )).all()

    if not rows:
        return CheckResult("reactions_1d_equals_3d", PASS, "No rows where pct_change_1d = pct_change_3d")

    details = [
        f"{r.symbol}  {r.event_date}  1d={r.pct_change_1d}  3d={r.pct_change_3d}"
        for r in rows
    ]
    return CheckResult(
        "reactions_1d_equals_3d", WARN,
        f"{len(rows)} row(s) with identical pct_change_1d and pct_change_3d (possible short trading window)",
        details,
    )


async def check_reactions_null_open_with_pct(session) -> CheckResult:
    rows = (await session.execute(
        select(Ticker.symbol, HistoricalReaction.event_date)
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.open_after.is_(None),
            (
                HistoricalReaction.pct_change_1d.is_not(None) |
                HistoricalReaction.pct_change_3d.is_not(None) |
                HistoricalReaction.pct_change_5d.is_not(None)
            ),
        )
        .order_by(Ticker.symbol, HistoricalReaction.event_date)
    )).all()

    if not rows:
        return CheckResult("reactions_null_open_with_pct", PASS, "No rows with null open_after but populated pct_change values")

    details = [f"{r.symbol}  {r.event_date}" for r in rows]
    return CheckResult(
        "reactions_null_open_with_pct", ERROR,
        f"{len(rows)} row(s) in impossible state: open_after is NULL but pct_change values are populated",
        details,
    )


async def check_reactions_eps_bounds(session) -> CheckResult:
    BOUND = Decimal("100")
    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.event_date,
            HistoricalReaction.eps_estimate,
            HistoricalReaction.eps_actual,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            (func.abs(HistoricalReaction.eps_estimate) > BOUND) |
            (func.abs(HistoricalReaction.eps_actual)   > BOUND)
        )
        .order_by(Ticker.symbol, HistoricalReaction.event_date)
    )).all()

    if not rows:
        return CheckResult("reactions_eps_bounds", PASS, "All EPS values within reasonable bounds (|value| ≤ 100)")

    details = [
        f"{r.symbol}  {r.event_date}  eps_estimate={r.eps_estimate}  eps_actual={r.eps_actual}"
        for r in rows
    ]
    return CheckResult(
        "reactions_eps_bounds", WARN,
        f"{len(rows)} row(s) with |eps_estimate| or |eps_actual| > 100 (likely parsing error)",
        details,
    )


async def check_tickers_no_reactions(session) -> CheckResult:
    cutoff = func.now() - text("interval '24 hours'")
    rows = (await session.execute(
        select(Ticker.symbol, Ticker.created_at)
        .where(
            Ticker.created_at < cutoff,
            ~select(HistoricalReaction.id)
            .where(HistoricalReaction.ticker_id == Ticker.id)
            .correlate(Ticker)
            .exists()
        )
        .order_by(Ticker.symbol)
    )).all()

    if not rows:
        return CheckResult("tickers_no_reactions", PASS, "All tickers seeded >24h ago have historical reactions")

    details = [f"{r.symbol}  (added {r.created_at.date()})" for r in rows]
    return CheckResult(
        "tickers_no_reactions", WARN,
        f"{len(rows)} ticker(s) in DB for >24h with zero historical reactions",
        details,
    )


async def check_tickers_uniform_outcome(session) -> CheckResult:
    """Flag tickers where every reaction has the same outcome — suspicious if ≥5 rows."""
    MIN_ROWS = 5
    subq = (
        select(
            HistoricalReaction.ticker_id,
            func.count(HistoricalReaction.id).label("total"),
            func.count(HistoricalReaction.id)
            .filter(HistoricalReaction.outcome == "unknown")
            .label("unknown_count"),
        )
        .group_by(HistoricalReaction.ticker_id)
        .having(func.count(HistoricalReaction.id) >= MIN_ROWS)
        .subquery()
    )

    # Count distinct outcomes per ticker
    outcome_counts = (
        select(
            HistoricalReaction.ticker_id,
            func.count(HistoricalReaction.id).label("total"),
            func.count(HistoricalReaction.outcome.distinct()).label("distinct_outcomes"),
        )
        .group_by(HistoricalReaction.ticker_id)
        .having(func.count(HistoricalReaction.id) >= MIN_ROWS)
        .subquery()
    )

    rows = (await session.execute(
        select(Ticker.symbol, outcome_counts.c.total, outcome_counts.c.distinct_outcomes)
        .join(outcome_counts, outcome_counts.c.ticker_id == Ticker.id)
        .where(outcome_counts.c.distinct_outcomes == 1)
        .order_by(Ticker.symbol)
    )).all()

    if not rows:
        return CheckResult("tickers_uniform_outcome", PASS, f"No tickers with ≥{MIN_ROWS} reactions all having the same outcome")

    details = [
        f"{r.symbol}  total_reactions={r.total}  distinct_outcomes={r.distinct_outcomes}"
        for r in rows
    ]
    return CheckResult(
        "tickers_uniform_outcome", WARN,
        f"{len(rows)} ticker(s) where all reactions share the same outcome (suspicious if many rows)",
        details,
    )


# ── Runner ────────────────────────────────────────────────────────────────────

CHECKS = [
    # Tickers
    check_ticker_missing_metadata,
    check_ticker_market_cap,
    check_ticker_duplicate_symbols,
    # Events
    check_events_stale_past,
    check_events_null_title,
    check_macro_events_with_ticker,
    check_ticker_events_null_ticker,
    # Historical reactions
    check_reactions_3d_equals_5d,
    check_reactions_1d_equals_3d,
    check_reactions_null_open_with_pct,
    check_reactions_eps_bounds,
    check_tickers_no_reactions,
    check_tickers_uniform_outcome,
]


def _icon(level: str) -> str:
    return {"pass": "✓", "warn": "⚠", "error": "✗"}.get(level, "?")


async def main() -> int:
    results: list[CheckResult] = []

    async with AsyncSessionLocal() as session:
        for check_fn in CHECKS:
            try:
                result = await check_fn(session)
            except Exception as exc:
                result = CheckResult(
                    check_fn.__name__, ERROR,
                    f"Check raised an exception: {exc}",
                )
            results.append(result)

    passed  = sum(1 for r in results if r.level == PASS)
    warned  = sum(1 for r in results if r.level == WARN)
    errored = sum(1 for r in results if r.level == ERROR)

    # Summary line
    parts = []
    if passed:  parts.append(f"✓ {passed} passed")
    if warned:  parts.append(f"⚠ {warned} warning{'s' if warned != 1 else ''}")
    if errored: parts.append(f"✗ {errored} error{'s' if errored != 1 else ''}")
    print("\n" + "  ".join(parts) + "\n")

    # Detail lines — passes last, errors first
    order = {ERROR: 0, WARN: 1, PASS: 2}
    for result in sorted(results, key=lambda r: order[r.level]):
        icon = _icon(result.level)
        print(f"  {icon}  {result.name}")
        print(f"     {result.message}")
        for row in result.rows:
            print(f"       · {row}")
        if result.rows:
            print()

    return 1 if errored else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
