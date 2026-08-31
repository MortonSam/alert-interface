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

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.alert_pick import AlertPick, AlertPickEvaluation
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.rv_snapshot import RVSnapshot
from app.models.system_metadata import SystemMetadata
from app.models.ticker import Ticker
from app.models.watchlist import WatchlistTicker
from app.services import chain_store


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
        EventType.EARNINGS, EventType.FDA, EventType.EX_DIVIDEND,
        EventType.PRODUCT_LAUNCH, EventType.SPLIT, EventType.ANALYST_ACTION,
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
    total = await session.scalar(
        select(func.count(HistoricalReaction.id)).where(
            HistoricalReaction.pct_change_3d.is_not(None),
            HistoricalReaction.pct_change_5d.is_not(None),
        )
    )
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
    rate = len(rows) / total * 100 if total else 0
    level = ERROR if rate > 1.0 else WARN
    return CheckResult(
        "reactions_3d_equals_5d", level,
        f"{len(rows)} row(s) ({rate:.2f}%) with identical pct_change_3d and pct_change_5d"
        + (" (coincidental price equality)" if level == WARN
           else " (rollforward bug — >1% of rows affected)"),
        details,
    )


async def check_reactions_1d_equals_3d(session) -> CheckResult:
    total = await session.scalar(
        select(func.count(HistoricalReaction.id)).where(
            HistoricalReaction.pct_change_1d.is_not(None),
            HistoricalReaction.pct_change_3d.is_not(None),
        )
    )
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
    rate = len(rows) / total * 100 if total else 0
    level = ERROR if rate > 1.0 else WARN
    return CheckResult(
        "reactions_1d_equals_3d", level,
        f"{len(rows)} row(s) ({rate:.2f}%) with identical pct_change_1d and pct_change_3d"
        + (" (coincidental price equality)" if level == WARN
           else " (>1% of rows affected — possible stale price data)"),
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
    BOUND = Decimal("500")
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
        return CheckResult("reactions_eps_bounds", PASS, "All EPS values within reasonable bounds (|value| ≤ 500)")

    details = [
        f"{r.symbol}  {r.event_date}  eps_estimate={r.eps_estimate}  eps_actual={r.eps_actual}"
        for r in rows
    ]
    return CheckResult(
        "reactions_eps_bounds", WARN,
        f"{len(rows)} row(s) with |eps_estimate| or |eps_actual| > 500 (likely parsing error)",
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


async def check_duplicate_future_earnings(session) -> CheckResult:
    """Flag tickers with 2+ future earnings events within 45 days of each other."""
    today = date.today()
    rows = (await session.execute(
        select(Ticker.symbol, Event.event_date)
        .join(Ticker, Event.ticker_id == Ticker.id)
        .where(
            Ticker.is_active.is_(True),
            Event.event_type == EventType.EARNINGS,
            Event.event_date >= today,
        )
        .order_by(Ticker.symbol, Event.event_date)
    )).all()

    from collections import defaultdict
    by_sym: dict[str, list[date]] = defaultdict(list)
    for sym, edate in rows:
        by_sym[sym].append(edate)

    dupes: list[str] = []
    for sym, dates in sorted(by_sym.items()):
        if len(dates) < 2:
            continue
        for i in range(len(dates) - 1):
            if (dates[i + 1] - dates[i]).days <= 45:
                dupes.append(f"{sym}  {', '.join(d.isoformat() for d in dates)}")
                break

    if not dupes:
        return CheckResult("duplicate_future_earnings", PASS, "No tickers with duplicate future earnings within 45 days")

    return CheckResult(
        "duplicate_future_earnings", ERROR,
        f"{len(dupes)} ticker(s) with 2+ future earnings events within 45 days",
        dupes,
    )


async def check_iv_history_out_of_band(session) -> CheckResult:
    """Flag iv_history rows in last 7 days with atm_iv < 0.05 or > 4.0."""
    cutoff = date.today() - timedelta(days=7)
    rows = (await session.execute(
        text("""
            SELECT symbol, date, atm_iv
            FROM iv_history
            WHERE date >= :cutoff
              AND atm_iv IS NOT NULL
              AND (atm_iv < 0.05 OR atm_iv > 4.0)
            ORDER BY date DESC, symbol
        """),
        {"cutoff": cutoff}
    )).all()

    if not rows:
        return CheckResult("iv_history_out_of_band", PASS, "No out-of-band ATM IV values in last 7 days")

    details = [f"{r.symbol}  {r.date}  atm_iv={float(r.atm_iv):.4f}" for r in rows]
    return CheckResult(
        "iv_history_out_of_band", WARN,
        f"{len(rows)} iv_history row(s) with atm_iv outside [0.05, 4.0] in last 7 days",
        details,
    )


async def check_frozen_price_history(session) -> CheckResult:
    """Flag active tickers whose last 10 price rows all share the same close."""
    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT ticker_id, close_after,
                   ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY event_date DESC) AS rn
            FROM historical_reactions
            WHERE close_after IS NOT NULL
        ),
        uniform AS (
            SELECT r.ticker_id,
                   COUNT(*) AS n,
                   COUNT(DISTINCT r.close_after) AS distinct_closes
            FROM recent r
            WHERE r.rn <= 10
            GROUP BY r.ticker_id
            HAVING COUNT(*) >= 5 AND COUNT(DISTINCT r.close_after) = 1
        )
        SELECT t.symbol, u.n, u.distinct_closes
        FROM uniform u
        JOIN tickers t ON t.id = u.ticker_id
        WHERE t.is_active = true
        ORDER BY t.symbol
    """))).all()

    if not rows:
        return CheckResult("frozen_price_history", PASS, "No active tickers with frozen close prices in recent reactions")

    details = [f"{r.symbol}  last {r.n} closes all identical" for r in rows]
    return CheckResult(
        "frozen_price_history", WARN,
        f"{len(rows)} active ticker(s) with frozen close prices (delisted or halted?)",
        details,
    )


async def check_rv_snapshot_stale(session) -> CheckResult:
    """ERROR if the latest rv_snapshots date is more than 3 calendar days old."""
    latest_date = await session.scalar(select(func.max(RVSnapshot.as_of_date)))

    if latest_date is None:
        return CheckResult("rv_snapshot_stale", ERROR, "No rv_snapshots rows exist")

    age = (date.today() - latest_date).days
    if age <= 3:
        return CheckResult(
            "rv_snapshot_stale", PASS,
            f"Latest rv_snapshot is {latest_date} ({age} day(s) old)",
        )
    return CheckResult(
        "rv_snapshot_stale", ERROR,
        f"Latest rv_snapshot is {latest_date} ({age} days old, threshold 3)",
    )


async def check_rv_rank_bounds(session) -> CheckResult:
    """ERROR listing any rv_rank outside 0-100 or rv_20d outside 0.01-5.0."""
    bad_filter = (
        (RVSnapshot.rv_rank.is_not(None) & ((RVSnapshot.rv_rank < 0) | (RVSnapshot.rv_rank > 100))) |
        (RVSnapshot.rv_20d.is_not(None) & ((RVSnapshot.rv_20d < Decimal("0.01")) | (RVSnapshot.rv_20d > Decimal("5.0"))))
    )
    total = await session.scalar(select(func.count(RVSnapshot.id)).where(bad_filter))

    if not total:
        return CheckResult("rv_rank_bounds", PASS, "All rv_rank in [0, 100] and rv_20d in [0.01, 5.0]")

    rows = (await session.execute(
        select(RVSnapshot.symbol, RVSnapshot.as_of_date, RVSnapshot.rv_rank, RVSnapshot.rv_20d)
        .where(bad_filter)
        .order_by(RVSnapshot.as_of_date.desc(), RVSnapshot.symbol)
        .limit(50)
    )).all()

    details = [
        f"{r.symbol}  {r.as_of_date}  rv_rank={r.rv_rank}  rv_20d={r.rv_20d}"
        for r in rows
    ]
    return CheckResult(
        "rv_rank_bounds", ERROR,
        f"{total} row(s) with rv_rank outside [0, 100] or rv_20d outside [0.01, 5.0] (showing first 50)",
        details,
    )


async def check_rv_data_error_tickers(session) -> CheckResult:
    """WARN listing tickers whose latest rv_snapshot has status='data_error' (extreme returns)."""
    # Subquery: latest as_of_date per symbol
    latest_sq = (
        select(RVSnapshot.symbol, func.max(RVSnapshot.as_of_date).label("max_date"))
        .group_by(RVSnapshot.symbol)
        .subquery()
    )
    rows = (await session.execute(
        select(RVSnapshot.symbol, RVSnapshot.as_of_date)
        .join(latest_sq, (RVSnapshot.symbol == latest_sq.c.symbol) & (RVSnapshot.as_of_date == latest_sq.c.max_date))
        .where(RVSnapshot.status == "data_error")
        .order_by(RVSnapshot.symbol)
    )).all()

    if not rows:
        return CheckResult("rv_data_error_tickers", PASS, "No tickers excluded for extreme returns")

    details = [f"{r.symbol}  as_of={r.as_of_date}" for r in rows]
    return CheckResult(
        "rv_data_error_tickers", WARN,
        f"{len(rows)} ticker(s) excluded from RV (extreme returns, likely bad split adjustment)",
        details,
    )


async def check_recommendations_freshness(session) -> CheckResult:
    """WARN if fewer than 300 active tickers have a recommendation fetched within 7 days."""
    cutoff = func.now() - text("interval '7 days'")
    fresh_count = await session.scalar(
        select(func.count(func.distinct(AnalystRecommendation.ticker_id)))
        .join(Ticker, Ticker.id == AnalystRecommendation.ticker_id)
        .where(Ticker.is_active.is_(True), AnalystRecommendation.fetched_at >= cutoff)
    )
    total_active = await session.scalar(
        select(func.count(Ticker.id)).where(Ticker.is_active.is_(True))
    )

    if fresh_count >= 300:
        return CheckResult(
            "recommendations_freshness", PASS,
            f"{fresh_count}/{total_active} active tickers have recommendations fetched within 7 days",
        )
    return CheckResult(
        "recommendations_freshness", WARN,
        f"{fresh_count}/{total_active} active tickers have recommendations fetched within 7 days (below 300 threshold)",
    )


async def check_recommendations_bounds(session) -> CheckResult:
    """ERROR listing rows where any count is negative or total analysts > 100."""
    total_col = (
        AnalystRecommendation.strong_buy + AnalystRecommendation.buy +
        AnalystRecommendation.hold + AnalystRecommendation.sell +
        AnalystRecommendation.strong_sell
    )
    bad_filter = (
        (AnalystRecommendation.strong_buy < 0) | (AnalystRecommendation.buy < 0) |
        (AnalystRecommendation.hold < 0) | (AnalystRecommendation.sell < 0) |
        (AnalystRecommendation.strong_sell < 0) | (total_col > 100)
    )
    total = await session.scalar(select(func.count(AnalystRecommendation.id)).where(bad_filter))

    if not total:
        return CheckResult("recommendations_bounds", PASS, "All recommendation counts non-negative and total ≤ 100")

    rows = (await session.execute(
        select(
            Ticker.symbol, AnalystRecommendation.period,
            AnalystRecommendation.strong_buy, AnalystRecommendation.buy,
            AnalystRecommendation.hold, AnalystRecommendation.sell,
            AnalystRecommendation.strong_sell,
        )
        .join(Ticker, Ticker.id == AnalystRecommendation.ticker_id)
        .where(bad_filter)
        .order_by(AnalystRecommendation.period.desc(), Ticker.symbol)
        .limit(50)
    )).all()

    details = [
        f"{r.symbol}  {r.period}  SB={r.strong_buy} B={r.buy} H={r.hold} S={r.sell} SS={r.strong_sell}"
        f" total={r.strong_buy + r.buy + r.hold + r.sell + r.strong_sell}"
        for r in rows
    ]
    return CheckResult(
        "recommendations_bounds", ERROR,
        f"{total} row(s) with negative count or total > 100 (showing first 50)",
        details,
    )


async def check_pick_lifecycle(session) -> CheckResult:
    """ERROR listing open picks with past expiration or closed picks with null close data."""
    today_str = date.today().isoformat()

    open_expired = (await session.execute(
        select(AlertPick.symbol, AlertPick.status, AlertPick.expiration)
        .where(
            AlertPick.status == "open",
            AlertPick.expiration.is_not(None),
            AlertPick.expiration < today_str,
        )
        .order_by(AlertPick.symbol)
    )).all()

    closed_null = (await session.execute(
        select(AlertPick.symbol, AlertPick.status, AlertPick.closed_at, AlertPick.close_price)
        .where(
            AlertPick.status != "open",
            (AlertPick.closed_at.is_(None)) | (AlertPick.close_price.is_(None)),
        )
        .order_by(AlertPick.symbol)
    )).all()

    if not open_expired and not closed_null:
        return CheckResult("pick_lifecycle", PASS, "All picks have consistent status/expiration/close data")

    details: list[str] = []
    for r in open_expired:
        details.append(f"{r.symbol}  status=open  expiration={r.expiration} (past)")
    for r in closed_null:
        ca = "null" if r.closed_at is None else str(r.closed_at.date())
        cp = "null" if r.close_price is None else str(r.close_price)
        details.append(f"{r.symbol}  status={r.status}  closed_at={ca}  close_price={cp}")

    return CheckResult(
        "pick_lifecycle", ERROR,
        f"{len(details)} pick(s): {len(open_expired)} open with past expiration, {len(closed_null)} closed with null close data",
        details,
    )


async def check_inactive_leakage(session) -> CheckResult:
    """ERROR listing inactive tickers in watchlists, open picks, or today's evaluations."""
    inactive = (await session.execute(
        select(Ticker.id, Ticker.symbol).where(Ticker.is_active.is_(False))
    )).all()

    if not inactive:
        return CheckResult("inactive_leakage", PASS, "No inactive tickers to check")

    inactive_ids = {r.id for r in inactive}
    inactive_syms = {r.symbol for r in inactive}
    id_to_sym = {r.id: r.symbol for r in inactive}

    details: list[str] = []

    # In watchlists
    wl_tids = (await session.execute(
        select(func.distinct(WatchlistTicker.ticker_id))
        .where(WatchlistTicker.ticker_id.in_(inactive_ids))
    )).scalars().all()
    for tid in wl_tids:
        details.append(f"{id_to_sym.get(tid, str(tid))}  in watchlist")

    # In open alert_picks
    pick_syms = (await session.execute(
        select(func.distinct(AlertPick.symbol))
        .where(AlertPick.status == "open", AlertPick.symbol.in_(inactive_syms))
    )).scalars().all()
    for sym in pick_syms:
        details.append(f"{sym}  open alert_pick")

    # In today's evaluations
    eval_syms = (await session.execute(
        select(func.distinct(AlertPickEvaluation.symbol))
        .where(
            AlertPickEvaluation.symbol.in_(inactive_syms),
            func.date(AlertPickEvaluation.evaluated_at) == date.today(),
        )
    )).scalars().all()
    for sym in eval_syms:
        details.append(f"{sym}  in today's evaluations")

    if not details:
        return CheckResult(
            "inactive_leakage", PASS,
            f"No inactive tickers leaking into watchlists, picks, or evaluations ({len(inactive)} inactive checked)",
        )
    return CheckResult(
        "inactive_leakage", ERROR,
        f"{len(details)} inactive-ticker reference(s) found",
        sorted(details),
    )


async def check_quote_sanity(session) -> CheckResult:
    """WARN listing active tickers whose latest stored close is ≤ 0 or moved >60% without a split."""
    # Part 1: latest iv_history current_price ≤ 0
    bad_price = (await session.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (ih.symbol) ih.symbol, ih.date, ih.current_price
            FROM iv_history ih
            JOIN tickers t ON t.symbol = ih.symbol AND t.is_active = true
            WHERE ih.current_price IS NOT NULL
            ORDER BY ih.symbol, ih.date DESC
        )
        SELECT symbol, date, current_price FROM latest WHERE current_price <= 0
        ORDER BY symbol
    """))).all()

    # Part 2: >60% day-over-day move in last 30 days without a split event
    big_moves = (await session.execute(text("""
        WITH daily AS (
            SELECT ih.symbol, ih.date, ih.current_price,
                   LAG(ih.current_price) OVER (PARTITION BY ih.symbol ORDER BY ih.date) AS prev_price
            FROM iv_history ih
            JOIN tickers t ON t.symbol = ih.symbol AND t.is_active = true
            WHERE ih.current_price IS NOT NULL AND ih.current_price > 0
              AND ih.date >= CURRENT_DATE - 30
        )
        SELECT d.symbol, d.date, d.current_price, d.prev_price,
               ABS(d.current_price - d.prev_price) / d.prev_price AS move_pct
        FROM daily d
        WHERE d.prev_price > 0
          AND ABS(d.current_price - d.prev_price) / d.prev_price > 0.60
          AND NOT EXISTS (
              SELECT 1 FROM events e
              JOIN tickers t2 ON t2.id = e.ticker_id
              WHERE t2.symbol = d.symbol AND e.event_type = 'split' AND e.event_date = d.date
          )
        ORDER BY d.date DESC, d.symbol
        LIMIT 50
    """))).all()

    if not bad_price and not big_moves:
        return CheckResult("quote_sanity", PASS, "All active tickers have positive latest close and no unexplained >60% moves")

    details: list[str] = []
    for r in bad_price:
        details.append(f"{r.symbol}  {r.date}  close={float(r.current_price):.2f} (non-positive)")
    for r in big_moves:
        details.append(
            f"{r.symbol}  {r.date}  {float(r.prev_price):.2f} -> {float(r.current_price):.2f}"
            f" ({float(r.move_pct) * 100:.0f}% move, no split)"
        )

    return CheckResult(
        "quote_sanity", WARN,
        f"{len(bad_price)} non-positive close(s), {len(big_moves)} unexplained >60% move(s)",
        details,
    )


async def check_chain_coverage(session) -> CheckResult:
    """Percent of active tickers with a chain no older than 2 trading days."""
    active_syms = (await session.execute(
        select(Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
    )).scalars().all()

    if not active_syms:
        return CheckResult("chain_coverage", PASS, "No active tickers")

    stale: list[str] = []
    for sym in active_syms:
        exps = await chain_store.get_ingested_expirations(session, sym)
        fresh = False
        for exp in reversed(exps):
            result = await chain_store.get_chain(session, sym, exp)
            if result:
                _, chain_last_trade = result
                if chain_store.is_fresh(chain_last_trade):
                    fresh = True
                    break
        if not fresh:
            stale.append(sym)

    covered = len(active_syms) - len(stale)
    pct = covered / len(active_syms) * 100

    if pct >= 90:
        return CheckResult(
            "chain_coverage", PASS,
            f"{covered}/{len(active_syms)} active tickers ({pct:.0f}%) have a fresh chain",
        )

    details = [f"{sym}  no fresh chain" for sym in stale]
    return CheckResult(
        "chain_coverage", WARN,
        f"{covered}/{len(active_syms)} ({pct:.0f}%) active tickers have a fresh chain (below 90% threshold)",
        details,
    )


# ── Runner ────────────────────────────────────────────────────────────────────

CHECKS = [
    # Tickers
    check_ticker_missing_metadata,
    check_ticker_market_cap,
    check_ticker_duplicate_symbols,
    check_frozen_price_history,
    check_duplicate_future_earnings,
    check_inactive_leakage,
    check_quote_sanity,
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
    # RV snapshots
    check_rv_snapshot_stale,
    check_rv_rank_bounds,
    check_rv_data_error_tickers,
    # Analyst recommendations
    check_recommendations_freshness,
    check_recommendations_bounds,
    # Alert picks
    check_pick_lifecycle,
    # IV history
    check_iv_history_out_of_band,
    # Options chains
    check_chain_coverage,
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
