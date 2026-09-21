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
from app.models.analyst_reaction_stats import AnalystReactionStats
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.earnings_feature import EarningsFeature
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.rv_snapshot import RVSnapshot
from app.models.magnitude_trend_snapshot import MagnitudeTrendSnapshot
from app.models.put_call_snapshot import PutCallSnapshot
from app.models.sector_peer_snapshot import SectorPeerSnapshot
from app.models.shadow_pick import ShadowPick
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
    # Analyst actions use close-to-close (no open_after), so exclude them.
    rows = (await session.execute(
        select(Ticker.symbol, HistoricalReaction.event_date)
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.open_after.is_(None),
            HistoricalReaction.event_type != "analyst_action",
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


async def check_analyst_reactions_missing_prices(session) -> CheckResult:
    """analyst_action rows with pct_change_1d must have close_before and close_after."""
    rows = (await session.execute(
        select(Ticker.symbol, HistoricalReaction.event_date)
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == "analyst_action",
            HistoricalReaction.pct_change_1d.isnot(None),
            (
                HistoricalReaction.close_before.is_(None) |
                HistoricalReaction.close_after.is_(None)
            ),
        )
        .order_by(Ticker.symbol, HistoricalReaction.event_date)
    )).all()

    if not rows:
        return CheckResult(
            "analyst_reactions_missing_prices", PASS,
            "All analyst reactions with moves have close_before and close_after",
        )

    details = [f"{r.symbol}  {r.event_date}" for r in rows]
    return CheckResult(
        "analyst_reactions_missing_prices", ERROR,
        f"{len(rows)} analyst_action row(s) with pct_change_1d but null close_before/close_after",
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


async def check_iv_history_price_drift(session) -> CheckResult:
    """WARN if any iv_history row from the last 7 days drifts >20% from prior row's close (within 5 days)."""
    cutoff = date.today() - timedelta(days=7)
    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT symbol, date, current_price,
                   LAG(current_price) OVER (PARTITION BY symbol ORDER BY date) AS prev_price,
                   LAG(date) OVER (PARTITION BY symbol ORDER BY date) AS prev_date
            FROM iv_history
            WHERE current_price IS NOT NULL
              AND current_price != 'NaN'::numeric
              AND current_price > 0
        )
        SELECT symbol, date, current_price, prev_price, prev_date,
               ABS(current_price - prev_price) / prev_price AS drift
        FROM recent
        WHERE date >= :cutoff
          AND prev_price IS NOT NULL AND prev_price > 0
          AND (date - prev_date) <= 5
          AND ABS(current_price - prev_price) / prev_price > 0.20
          AND NOT EXISTS (
              SELECT 1 FROM events e
              JOIN tickers t ON t.id = e.ticker_id
              WHERE t.symbol = recent.symbol AND e.event_type = 'split' AND e.event_date = recent.date
          )
        ORDER BY date DESC, symbol
        LIMIT 50
    """), {"cutoff": cutoff})).all()

    if not rows:
        return CheckResult("iv_history_price_drift", PASS, "No iv_history price drift >20% in last 7 days")

    details = [
        f"{r.symbol}  {r.date}  {float(r.prev_price):.2f} -> {float(r.current_price):.2f}"
        f" ({float(r.drift) * 100:.0f}% drift)"
        for r in rows
    ]
    return CheckResult(
        "iv_history_price_drift", WARN,
        f"{len(rows)} iv_history row(s) with >20% price drift in last 7 days (corrupt snapshot?)",
        details,
    )


async def check_nan_numeric_values(session) -> CheckResult:
    """ERROR if any numeric column in key tables contains PostgreSQL NaN.

    PostgreSQL 'NaN'::numeric is distinct from NULL and invisible to
    IS NULL checks.  Python float('nan') fails all comparisons, so NaN
    rows silently poison filters and aggregates.
    """
    # (table, [numeric_columns])
    NAN_TABLES = [
        ("earnings_features", [
            "beat_rate", "median_1d_beat", "median_1d_miss", "weighted_1d",
            "buy_share_latest", "buy_share_60d_ago", "analyst_delta",
            "momentum_20d", "prior_avg_abs_1d", "atm_iv",
            "prior_avg_abs_5d", "prior_up_5d_rate",
            "actual_1d", "actual_3d", "actual_5d",
        ]),
        ("alert_picks", [
            "close_price", "option_pnl_dollars", "option_pnl_pct",
            "entry_price", "cost_to_enter", "stock_move_5d",
        ]),
        ("alert_pick_evaluations", [
            "momentum_20d", "expected_move_pct", "implied_move_pct",
        ]),
        ("shadow_picks", [
            "probability", "threshold_used", "actual_5d",
        ]),
        ("credit_shadow_picks", [
            "spot", "expected_pct", "implied_pct",
            "short_put_strike", "short_call_strike",
            "long_put_strike", "long_call_strike",
            "credit_received", "max_loss",
            "close_value", "pnl_dollars", "pnl_pct", "stock_move_5d",
        ]),
    ]

    bad: list[str] = []
    for table, cols in NAN_TABLES:
        # Check if table exists first
        exists = (await session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
        ), {"t": table})).scalar()
        if not exists:
            continue
        for col in cols:
            try:
                cnt = (await session.execute(text(
                    f"SELECT count(*) FROM {table} WHERE {col} = 'NaN'::numeric"
                ))).scalar()
            except Exception:
                continue  # column doesn't exist yet
            if cnt and cnt > 0:
                bad.append(f"{table}.{col}: {cnt} NaN row(s)")

    if not bad:
        return CheckResult("nan_numeric_values", PASS, "No NaN values in any numeric column")
    return CheckResult("nan_numeric_values", ERROR, f"NaN found in {len(bad)} column(s)", bad)


# ── Earnings features ─────────────────────────────────────────────────────────

async def check_earnings_features_row_count(session) -> CheckResult:
    """ERROR if earnings_features has fewer than 9,000 rows."""
    count = (await session.execute(
        select(func.count()).select_from(EarningsFeature)
    )).scalar_one()
    if count >= 9000:
        return CheckResult("earnings_features_row_count", PASS, f"{count:,} earnings_features rows")
    return CheckResult("earnings_features_row_count", ERROR, f"Only {count:,} earnings_features rows (need >= 9,000)")


async def check_earnings_features_momentum_nulls(session) -> CheckResult:
    """ERROR if momentum_20d null rate exceeds 1% in earnings_features."""
    total = (await session.execute(
        select(func.count()).select_from(EarningsFeature)
    )).scalar_one()
    if total == 0:
        return CheckResult("earnings_features_momentum_nulls", WARN, "No earnings_features rows")
    null_count = (await session.execute(
        select(func.count()).select_from(EarningsFeature)
        .where(EarningsFeature.momentum_20d.is_(None))
    )).scalar_one()
    rate = null_count / total * 100
    if rate < 1.0:
        return CheckResult(
            "earnings_features_momentum_nulls", PASS,
            f"momentum_20d null rate {rate:.2f}% ({null_count:,}/{total:,})",
        )
    return CheckResult(
        "earnings_features_momentum_nulls", ERROR,
        f"momentum_20d null rate {rate:.1f}% ({null_count:,}/{total:,}), expected < 1%",
    )


async def check_v2_pick_integrity(session) -> CheckResult:
    """ERROR if any v2 alert_pick has null receipt, null strikes, null cost, or entry_price <= 0."""
    rows = (await session.execute(
        select(AlertPick.symbol, AlertPick.generated_at,
               AlertPick.receipt, AlertPick.suggested_strike,
               AlertPick.suggested_spread_strike, AlertPick.cost_to_enter,
               AlertPick.entry_price)
        .where(AlertPick.algo_version.like("v2%"))
    )).all()
    if not rows:
        return CheckResult("v2_pick_integrity", PASS, "No v2 picks to check")
    bad: list[str] = []
    for r in rows:
        issues: list[str] = []
        if r.receipt is None:
            issues.append("null receipt")
        if r.suggested_strike is None:
            issues.append("null strike")
        if r.suggested_spread_strike is None:
            issues.append("null spread_strike")
        if r.cost_to_enter is None:
            issues.append("null cost")
        if r.entry_price is None or float(r.entry_price) <= 0:
            issues.append(f"entry_price={r.entry_price}")
        if issues:
            dt = r.generated_at.strftime("%Y-%m-%d") if r.generated_at else "?"
            bad.append(f"{r.symbol} ({dt}): {', '.join(issues)}")
    if not bad:
        return CheckResult("v2_pick_integrity", PASS, f"All {len(rows)} v2 picks have receipt, strikes, cost, and entry_price > 0")
    return CheckResult("v2_pick_integrity", ERROR, f"{len(bad)} v2 pick(s) with missing data", bad)


async def check_v2_exit_date(session) -> CheckResult:
    """ERROR if any v2 pick is missing exit_date or is open > 2 trading days past exit_date."""
    v2_picks = (await session.execute(
        select(AlertPick.symbol, AlertPick.generated_at, AlertPick.exit_date, AlertPick.status)
        .where(AlertPick.algo_version.like("v2%"))
    )).all()

    if not v2_picks:
        return CheckResult("v2_exit_date", PASS, "No v2 picks to check")

    bad: list[str] = []
    today = date.today()

    for r in v2_picks:
        dt = r.generated_at.strftime("%Y-%m-%d") if r.generated_at else "?"
        if r.exit_date is None:
            bad.append(f"{r.symbol} ({dt}): missing exit_date")
        elif r.status == "open" and r.exit_date:
            # Check if more than 2 trading days past exit_date
            # Approximate: each calendar day past exit_date that is a weekday counts
            days_past = (today - r.exit_date).days
            if days_past > 3:  # 3 calendar days ~ 2 trading days with buffer
                bad.append(f"{r.symbol} ({dt}): open {days_past} day(s) past exit_date {r.exit_date}")

    if not bad:
        return CheckResult("v2_exit_date", PASS, f"All {len(v2_picks)} v2 picks have exit_date and none overdue")

    return CheckResult("v2_exit_date", ERROR, f"{len(bad)} v2 pick(s) with exit_date issues", bad)


async def check_shadow_pick_count(session) -> CheckResult:
    """WARN if latest nightly shadow_pick count does not match evaluation count."""
    from sqlalchemy import Date as SADate

    # Latest evaluation batch date
    max_eval_date = (await session.execute(
        select(func.max(func.cast(AlertPickEvaluation.evaluated_at, SADate)))
        .where(AlertPickEvaluation.source == "nightly")
    )).scalar()

    if max_eval_date is None:
        return CheckResult("shadow_pick_count", PASS, "No nightly evaluations yet")

    eval_count = (await session.execute(
        select(func.count()).select_from(AlertPickEvaluation)
        .where(
            AlertPickEvaluation.source == "nightly",
            func.cast(AlertPickEvaluation.evaluated_at, SADate) == max_eval_date,
        )
    )).scalar_one()

    # Shadow picks for the same date range (shadow_eval uses event_date, not decided_at)
    shadow_count = (await session.execute(
        select(func.count()).select_from(ShadowPick)
        .where(func.cast(ShadowPick.decided_at, SADate) == max_eval_date)
    )).scalar_one()

    if eval_count == shadow_count:
        return CheckResult(
            "shadow_pick_count", PASS,
            f"Shadow picks ({shadow_count}) match evaluations ({eval_count}) for {max_eval_date}",
        )
    return CheckResult(
        "shadow_pick_count", WARN,
        f"Shadow picks ({shadow_count}) != evaluations ({eval_count}) for {max_eval_date}",
    )


async def check_credit_shadow_integrity(session) -> CheckResult:
    """ERROR if any credit_shadow_picks row has null strikes or credit <= 0."""
    # Check if table exists first
    exists = (await session.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'credit_shadow_picks')"
    ))).scalar()
    if not exists:
        return CheckResult("credit_shadow_integrity", PASS, "credit_shadow_picks table not yet created")

    bad_rows = (await session.execute(text("""
        SELECT id, symbol, event_date, credit_received
        FROM credit_shadow_picks
        WHERE short_put_strike IS NULL
           OR short_call_strike IS NULL
           OR long_put_strike IS NULL
           OR long_call_strike IS NULL
           OR credit_received IS NULL
           OR credit_received <= 0
        ORDER BY event_date DESC
    """))).all()

    if not bad_rows:
        total = (await session.execute(text(
            "SELECT count(*) FROM credit_shadow_picks"
        ))).scalar()
        return CheckResult(
            "credit_shadow_integrity", PASS,
            f"All {total} credit_shadow_picks have valid strikes and positive credit",
        )

    details = [f"{r.symbol} {r.event_date} credit={r.credit_received}" for r in bad_rows]
    return CheckResult(
        "credit_shadow_integrity", ERROR,
        f"{len(bad_rows)} credit_shadow_picks row(s) with null strikes or credit <= 0",
        details,
    )


async def check_reaction_pct_range(session) -> CheckResult:
    """ERROR if any historical_reaction pct_change_1d/3d/5d is outside [-95, 500]."""
    bad_filter = (
        (HistoricalReaction.pct_change_1d.is_not(None) & (
            (HistoricalReaction.pct_change_1d < Decimal("-95")) |
            (HistoricalReaction.pct_change_1d > Decimal("500"))
        )) |
        (HistoricalReaction.pct_change_3d.is_not(None) & (
            (HistoricalReaction.pct_change_3d < Decimal("-95")) |
            (HistoricalReaction.pct_change_3d > Decimal("500"))
        )) |
        (HistoricalReaction.pct_change_5d.is_not(None) & (
            (HistoricalReaction.pct_change_5d < Decimal("-95")) |
            (HistoricalReaction.pct_change_5d > Decimal("500"))
        ))
    )
    total = await session.scalar(select(func.count(HistoricalReaction.id)).where(bad_filter))
    if not total:
        return CheckResult("reaction_pct_range", PASS, "All reaction pct_change values in [-95, 500]")

    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.pct_change_3d,
            HistoricalReaction.pct_change_5d,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(bad_filter)
        .order_by(HistoricalReaction.event_date.desc())
        .limit(50)
    )).all()
    details = [
        f"{r.symbol}  {r.event_date}  1d={r.pct_change_1d}  3d={r.pct_change_3d}  5d={r.pct_change_5d}"
        for r in rows
    ]
    return CheckResult(
        "reaction_pct_range", ERROR,
        f"{total} reaction(s) with pct_change outside [-95, 500]",
        details,
    )


async def check_analyst_stats_median_range(session) -> CheckResult:
    """ERROR if any analyst_reaction_stats median is outside [-30, 30]."""
    bad_filter = (
        (AnalystReactionStats.median_1d_upgrade.is_not(None) & (
            (AnalystReactionStats.median_1d_upgrade < -30) |
            (AnalystReactionStats.median_1d_upgrade > 30)
        )) |
        (AnalystReactionStats.median_1d_downgrade.is_not(None) & (
            (AnalystReactionStats.median_1d_downgrade < -30) |
            (AnalystReactionStats.median_1d_downgrade > 30)
        ))
    )
    total = await session.scalar(select(func.count(AnalystReactionStats.id)).where(bad_filter))
    if not total:
        return CheckResult("analyst_stats_median_range", PASS, "All analyst medians in [-30, 30]")

    rows = (await session.execute(
        select(
            AnalystReactionStats.symbol,
            AnalystReactionStats.median_1d_upgrade,
            AnalystReactionStats.median_1d_downgrade,
        )
        .where(bad_filter)
        .limit(50)
    )).all()
    details = [
        f"{r.symbol}  median_up={r.median_1d_upgrade}  median_down={r.median_1d_downgrade}"
        for r in rows
    ]
    return CheckResult(
        "analyst_stats_median_range", ERROR,
        f"{total} analyst_reaction_stats row(s) with median outside [-30, 30]",
        details,
    )


async def check_analyst_stats_continuation_range(session) -> CheckResult:
    """ERROR if any analyst_reaction_stats continuation pct is outside [0, 100]."""
    bad_filter = (
        (AnalystReactionStats.upgrade_5d_continuation_pct.is_not(None) & (
            (AnalystReactionStats.upgrade_5d_continuation_pct < 0) |
            (AnalystReactionStats.upgrade_5d_continuation_pct > 100)
        )) |
        (AnalystReactionStats.downgrade_5d_continuation_pct.is_not(None) & (
            (AnalystReactionStats.downgrade_5d_continuation_pct < 0) |
            (AnalystReactionStats.downgrade_5d_continuation_pct > 100)
        ))
    )
    total = await session.scalar(select(func.count(AnalystReactionStats.id)).where(bad_filter))
    if not total:
        return CheckResult(
            "analyst_stats_continuation_range", PASS,
            "All analyst continuation rates in [0, 100]",
        )

    rows = (await session.execute(
        select(
            AnalystReactionStats.symbol,
            AnalystReactionStats.upgrade_5d_continuation_pct,
            AnalystReactionStats.downgrade_5d_continuation_pct,
        )
        .where(bad_filter)
        .limit(50)
    )).all()
    details = [
        f"{r.symbol}  up_cont={r.upgrade_5d_continuation_pct}  down_cont={r.downgrade_5d_continuation_pct}"
        for r in rows
    ]
    return CheckResult(
        "analyst_stats_continuation_range", ERROR,
        f"{total} analyst_reaction_stats row(s) with continuation pct outside [0, 100]",
        details,
    )


async def check_sector_peer_avg_range(session) -> CheckResult:
    """ERROR if any stored per-ticker avg abs 1d is outside [0.5, 40.0]."""
    rows = (await session.execute(
        select(SectorPeerSnapshot.symbol, SectorPeerSnapshot.avg_abs_1d)
        .where(
            SectorPeerSnapshot.avg_abs_1d.isnot(None),
            (SectorPeerSnapshot.avg_abs_1d < Decimal("0.5")) |
            (SectorPeerSnapshot.avg_abs_1d > Decimal("40.0")),
        )
        .order_by(SectorPeerSnapshot.symbol)
    )).all()

    if not rows:
        return CheckResult("sector_peer_avg_range", PASS,
                           "All stored per-ticker avg abs 1d in [0.5, 40.0]")

    details = [f"{r.symbol}  avg_abs_1d={float(r.avg_abs_1d):.2f}" for r in rows]
    return CheckResult(
        "sector_peer_avg_range", ERROR,
        f"{len(rows)} ticker(s) with stored avg abs 1d outside [0.5, 40.0]",
        details,
    )


async def check_sector_peer_sector_avg_range(session) -> CheckResult:
    """ERROR if any stored sector aggregate avg abs 1d is outside [1.0, 25.0]."""
    rows = (await session.execute(
        select(
            SectorPeerSnapshot.sector,
            SectorPeerSnapshot.sector_avg_abs_1d,
        )
        .where(
            SectorPeerSnapshot.sector_avg_abs_1d.isnot(None),
            (SectorPeerSnapshot.sector_avg_abs_1d < Decimal("1.0")) |
            (SectorPeerSnapshot.sector_avg_abs_1d > Decimal("25.0")),
        )
        .distinct(SectorPeerSnapshot.sector)
        .order_by(SectorPeerSnapshot.sector)
    )).all()

    if not rows:
        return CheckResult("sector_peer_sector_avg_range", PASS,
                           "All stored sector aggregate avg abs 1d in [1.0, 25.0]")

    details = [f"{r.sector}  sector_avg={float(r.sector_avg_abs_1d):.2f}" for r in rows]
    return CheckResult(
        "sector_peer_sector_avg_range", ERROR,
        f"{len(rows)} sector(s) with stored aggregate avg abs 1d outside [1.0, 25.0]",
        details,
    )


async def check_sector_peer_count_range(session) -> CheckResult:
    """ERROR if any sector's stored peer count is outside [5, 150]."""
    rows = (await session.execute(
        select(
            SectorPeerSnapshot.sector,
            SectorPeerSnapshot.sector_peer_count,
        )
        .where(
            (SectorPeerSnapshot.sector_peer_count < 5) |
            (SectorPeerSnapshot.sector_peer_count > 150),
        )
        .distinct(SectorPeerSnapshot.sector)
        .order_by(SectorPeerSnapshot.sector)
    )).all()

    if not rows:
        return CheckResult("sector_peer_count_range", PASS,
                           "All stored sector peer counts in [5, 150]")

    details = [f"{r.sector}  peer_count={r.sector_peer_count}" for r in rows]
    return CheckResult(
        "sector_peer_count_range", ERROR,
        f"{len(rows)} sector(s) with stored peer count outside [5, 150]",
        details,
    )


# ── Magnitude trend snapshots ────────────────────────────────────────────────

async def check_magnitude_trend_avg_range(session) -> CheckResult:
    """ERROR if any stored magnitude trend avg is outside [0.3, 40.0]."""
    rows = (await session.execute(
        select(
            MagnitudeTrendSnapshot.symbol,
            MagnitudeTrendSnapshot.recent_avg_abs_1d,
            MagnitudeTrendSnapshot.prior_avg_abs_1d,
        )
        .where(
            (MagnitudeTrendSnapshot.recent_avg_abs_1d.isnot(None)) |
            (MagnitudeTrendSnapshot.prior_avg_abs_1d.isnot(None)),
        )
    )).all()

    bad: list[str] = []
    for r in rows:
        for col_name, val in [("recent", r.recent_avg_abs_1d), ("prior", r.prior_avg_abs_1d)]:
            if val is not None and (val < Decimal("0.3") or val > Decimal("40.0")):
                bad.append(f"{r.symbol}  {col_name}_avg_abs_1d={float(val):.2f}")

    if not bad:
        return CheckResult("magnitude_trend_avg_range", PASS,
                           "All stored magnitude trend avgs in [0.3, 40.0]")

    return CheckResult(
        "magnitude_trend_avg_range", ERROR,
        f"{len(bad)} value(s) outside [0.3, 40.0]",
        bad,
    )


# ── Put/call ratio snapshots ────────────────────────────────────────────────

async def check_put_call_ratio_range(session) -> CheckResult:
    """Multi-tier put/call ratio validation.

    ERROR if stored ratio differs from put_total/call_total by >0.0001
          or is outside [0.005, 200].
    WARN  if ratio is outside [0.02, 10.0].
    """
    rows = (await session.execute(
        select(
            PutCallSnapshot.symbol,
            PutCallSnapshot.ratio,
            PutCallSnapshot.put_total,
            PutCallSnapshot.call_total,
            PutCallSnapshot.snapshot_date,
        )
        .where(PutCallSnapshot.ratio.isnot(None))
        .order_by(PutCallSnapshot.symbol, PutCallSnapshot.snapshot_date)
    )).all()

    errors: list[str] = []
    warns: list[str] = []

    for r in rows:
        ratio = float(r.ratio)
        # Arithmetic consistency: stored ratio must match put/call math
        if r.put_total is not None and r.call_total and r.call_total > 0:
            expected = r.put_total / r.call_total
            if abs(ratio - expected) > 0.0001:
                errors.append(
                    f"{r.symbol}  {r.snapshot_date}  ratio={ratio:.4f}  "
                    f"expected={expected:.4f}  (arithmetic mismatch)"
                )
                continue

        # Hard bounds
        if ratio < 0.005 or ratio > 200:
            errors.append(f"{r.symbol}  {r.snapshot_date}  ratio={ratio:.4f}  (outside [0.005, 200])")
            continue

        # Soft bounds (WARN)
        if ratio < 0.02 or ratio > 10.0:
            warns.append(f"{r.symbol}  {r.snapshot_date}  ratio={ratio:.4f}  (outside [0.02, 10.0])")

    if errors:
        return CheckResult(
            "put_call_ratio_range", ERROR,
            f"{len(errors)} ratio error(s), {len(warns)} warning(s)",
            errors + warns,
        )
    if warns:
        return CheckResult(
            "put_call_ratio_range", WARN,
            f"{len(warns)} ratio(s) outside [0.02, 10.0] (all arithmetically correct)",
            warns,
        )
    return CheckResult("put_call_ratio_range", PASS,
                       f"All {len(rows)} stored ratios arithmetically correct and in [0.02, 10.0]")


async def check_put_call_per_side_guard(session) -> CheckResult:
    """ERROR if any stored ratio has put_total or call_total < MIN_SIDE_CONTRACTS."""
    from app.constants import MIN_SIDE_CONTRACTS
    rows = (await session.execute(
        select(
            PutCallSnapshot.symbol,
            PutCallSnapshot.ratio,
            PutCallSnapshot.put_total,
            PutCallSnapshot.call_total,
            PutCallSnapshot.snapshot_date,
        )
        .where(
            PutCallSnapshot.ratio.isnot(None),
            (PutCallSnapshot.put_total < MIN_SIDE_CONTRACTS) |
            (PutCallSnapshot.call_total < MIN_SIDE_CONTRACTS),
        )
        .order_by(PutCallSnapshot.symbol, PutCallSnapshot.snapshot_date)
    )).all()

    if not rows:
        return CheckResult(
            "put_call_per_side_guard", PASS,
            f"No stored ratios with either side < {MIN_SIDE_CONTRACTS}",
        )

    details = [
        f"{r.symbol}  {r.snapshot_date}  put={r.put_total}  call={r.call_total}  ratio={float(r.ratio):.4f}"
        for r in rows
    ]
    return CheckResult(
        "put_call_per_side_guard", ERROR,
        f"{len(rows)} ratio(s) stored with a side below {MIN_SIDE_CONTRACTS} contracts",
        details,
    )


# ── Options-read coverage ───────────────────────────────────────────────────

async def check_options_read_coverage(session) -> CheckResult:
    """WARN if <90% of active tickers have an options-read for the latest chain date. ERROR <75%."""
    # Count active tickers
    total_active = (await session.execute(
        select(func.count()).select_from(Ticker).where(Ticker.is_active.is_(True))
    )).scalar_one()

    if total_active == 0:
        return CheckResult("options_read_coverage", PASS, "No active tickers")

    # Find the latest chain_last_trade date from any stored chain
    import json as _json
    chain_row = (await session.execute(
        select(SystemMetadata.value)
        .where(SystemMetadata.key.like("chain:%"))
        .limit(1)
    )).scalar_one_or_none()

    if chain_row is None:
        return CheckResult("options_read_coverage", WARN,
                           "No chains stored — cannot determine chain date")

    try:
        chain_date = _json.loads(chain_row).get("chain_last_trade", "")[:10]
    except Exception:
        chain_date = ""

    if not chain_date:
        return CheckResult("options_read_coverage", WARN,
                           "No chain_last_trade found in stored chains")

    # Count options-read cache keys for the latest chain date (v3 key format)
    pattern = f"options_read:v3:%:{chain_date}"
    cached_count = (await session.execute(
        select(func.count()).select_from(SystemMetadata)
        .where(SystemMetadata.key.like(pattern))
    )).scalar_one()

    pct = round(cached_count / total_active * 100, 1)

    if pct < 75:
        return CheckResult(
            "options_read_coverage", ERROR,
            f"Only {cached_count}/{total_active} ({pct}%) active tickers have an options-read for chain date {chain_date}",
        )
    if pct < 90:
        return CheckResult(
            "options_read_coverage", WARN,
            f"{cached_count}/{total_active} ({pct}%) active tickers have an options-read for chain date {chain_date}",
        )
    return CheckResult(
        "options_read_coverage", PASS,
        f"{cached_count}/{total_active} ({pct}%) active tickers have an options-read for chain date {chain_date}",
    )


# ── v3 reaction checks ───────────────────────────────────────────────────────

async def check_no_mixed_computation_version(session) -> CheckResult:
    """ERROR if earnings reactions have more than one distinct computation_version."""
    rows = (await session.execute(
        select(HistoricalReaction.computation_version)
        .where(HistoricalReaction.event_type == EventType.EARNINGS)
        .distinct()
    )).scalars().all()
    versions = sorted(rows)
    if len(versions) <= 1:
        return CheckResult(
            "no_mixed_computation_version", PASS,
            f"All earnings reactions at version {versions[0] if versions else '(none)'}",
        )
    return CheckResult(
        "no_mixed_computation_version", ERROR,
        f"Mixed computation versions: {versions}. Reseed incomplete.",
    )


async def check_report_timing_unknown_share(session) -> CheckResult:
    """WARN >10%, ERROR >25% of active tickers have unknown report timing on earnings reactions."""
    total_active = (await session.scalar(
        select(func.count(Ticker.id)).where(Ticker.is_active.is_(True))
    )) or 0
    if total_active == 0:
        return CheckResult("report_timing_unknown_share", PASS, "No active tickers")

    unknown_tickers = (await session.scalar(
        select(func.count(func.distinct(Ticker.id)))
        .select_from(Ticker)
        .join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(
            Ticker.is_active.is_(True),
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.report_timing == "unknown",
            HistoricalReaction.pct_change_1d.is_(None),
        )
    )) or 0

    pct = round(unknown_tickers / total_active * 100, 1)
    msg = f"{unknown_tickers}/{total_active} ({pct}%) active tickers have unknown report timing"

    if pct > 25:
        return CheckResult("report_timing_unknown_share", ERROR, msg)
    if pct > 10:
        return CheckResult("report_timing_unknown_share", WARN, msg)
    return CheckResult("report_timing_unknown_share", PASS, msg)


async def check_bmo_1d_vs_gap(session) -> CheckResult:
    """ERROR if any ticker's avg abs 1d < avg abs gap * 0.5 for bmo reactions.

    Ensures bmo reactions include the overnight gap. If the 1-day move is less
    than half the gap, the window is likely wrong.
    """
    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.open_after,
            HistoricalReaction.close_before,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.report_timing == "bmo",
            HistoricalReaction.pct_change_1d.isnot(None),
            HistoricalReaction.open_after.isnot(None),
            HistoricalReaction.close_before.isnot(None),
            HistoricalReaction.close_before > 0,
        )
    )).all()

    # Group by ticker
    from collections import defaultdict
    ticker_data: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        gap = abs(float(r.open_after) - float(r.close_before)) / float(r.close_before) * 100
        abs_1d = abs(float(r.pct_change_1d))
        ticker_data[r.symbol].append((abs_1d, gap))

    bad_tickers: list[str] = []
    for sym, pairs in ticker_data.items():
        if len(pairs) < 4:
            continue
        avg_abs_1d = sum(p[0] for p in pairs) / len(pairs)
        avg_abs_gap = sum(p[1] for p in pairs) / len(pairs)
        if avg_abs_gap > 0 and avg_abs_1d < avg_abs_gap * 0.5:
            bad_tickers.append(f"{sym}: avg_abs_1d={avg_abs_1d:.2f}%, avg_abs_gap={avg_abs_gap:.2f}%")

    if not bad_tickers:
        return CheckResult(
            "bmo_1d_vs_gap", PASS,
            f"All bmo tickers have avg abs 1d >= 50% of avg abs gap ({len(ticker_data)} tickers checked)",
        )
    return CheckResult(
        "bmo_1d_vs_gap", ERROR,
        f"{len(bad_tickers)} bmo ticker(s) have avg abs 1d < 50% of avg abs gap",
        bad_tickers[:20],
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
    check_analyst_reactions_missing_prices,
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
    # NaN guard
    check_nan_numeric_values,
    # IV history price drift
    check_iv_history_price_drift,
    # Earnings features
    check_earnings_features_row_count,
    check_earnings_features_momentum_nulls,
    # v2 pick integrity
    check_v2_pick_integrity,
    # v2 exit dates
    check_v2_exit_date,
    # Shadow picks
    check_shadow_pick_count,
    # Credit shadow picks
    check_credit_shadow_integrity,
    # Aggregate sanity bands
    check_reaction_pct_range,
    check_analyst_stats_median_range,
    check_analyst_stats_continuation_range,
    # Sector peers (stored snapshots)
    check_sector_peer_avg_range,
    check_sector_peer_sector_avg_range,
    check_sector_peer_count_range,
    # Magnitude trend (stored snapshots)
    check_magnitude_trend_avg_range,
    # Put/call ratio (stored snapshots)
    check_put_call_ratio_range,
    check_put_call_per_side_guard,
    # Options-read coverage
    check_options_read_coverage,
    # v3 reaction checks
    check_no_mixed_computation_version,
    check_report_timing_unknown_share,
    check_bmo_1d_vs_gap,
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
