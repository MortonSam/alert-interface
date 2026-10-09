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
from app.services.redact import redact

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
    figures: dict = field(default_factory=dict)    # numbers the step outcome and the digest carry (chain_coverage_pct)


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
            HistoricalReaction.event_type,
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
        f"{r.symbol}  {r.event_date}  [{r.event_type}]  3d={r.pct_change_3d}  5d={r.pct_change_5d}"
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
            HistoricalReaction.event_type,
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
        f"{r.symbol}  {r.event_date}  [{r.event_type}]  1d={r.pct_change_1d}  3d={r.pct_change_3d}"
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
            WHERE date >= :cutoff AND iv_source = 'courier'
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


async def check_price_history_stale(session) -> CheckResult:
    """WARN when an active ticker's last price bar is more than 3 sessions old.

    A warning, not an error: the quote, chart and RV reads already render these
    tickers absent with a reason, so nothing wrong reaches the screen.
    Also WARN when the last bar's close is more than 25% away from the stored quote
    (latest iv_history.current_price): the price series is probably another
    instrument. Reads rv_snapshots.last_bar_date/last_bar_close, written nightly.
    """
    from app.services.price_freshness import MAX_QUOTE_DIVERGENCE, MAX_STALE_SESSIONS, quote_divergence
    from app.services.trading_calendar import sessions_after

    rows = (await session.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (rs.symbol) rs.symbol, rs.as_of_date, rs.last_bar_date, rs.last_bar_close, rs.status
            FROM rv_snapshots rs
            JOIN tickers t ON t.symbol = rs.symbol AND t.is_active = true
            ORDER BY rs.symbol, rs.as_of_date DESC
        ),
        quote AS (
            SELECT DISTINCT ON (symbol) symbol, date AS quote_date, current_price
            FROM iv_history
            WHERE iv_source = 'courier' AND current_price IS NOT NULL AND current_price > 0
            ORDER BY symbol, date DESC
        )
        SELECT l.*, q.quote_date, q.current_price
        FROM latest l LEFT JOIN quote q ON q.symbol = l.symbol
        ORDER BY l.symbol
    """))).all()

    if not rows:
        return CheckResult("price_history_stale", WARN, "No rv_snapshots rows for active tickers")

    unmeasured = [r.symbol for r in rows if r.last_bar_date is None and r.status == "ok"]
    stale: list[str] = []
    diverged: list[str] = []
    no_recent_quote = 0
    for r in rows:
        if r.last_bar_date is None:
            continue
        missed = sessions_after(r.last_bar_date, r.as_of_date)
        if missed > MAX_STALE_SESSIONS:
            stale.append(f"{r.symbol}  last bar {r.last_bar_date} is {missed} sessions before snapshot {r.as_of_date}")
            continue
        # Compare like with like: only a quote stored within 3 sessions of the bar.
        if r.quote_date is None or max(
            sessions_after(r.quote_date, r.last_bar_date), sessions_after(r.last_bar_date, r.quote_date)
        ) > MAX_STALE_SESSIONS:
            no_recent_quote += 1
            continue
        div = quote_divergence(
            float(r.last_bar_close) if r.last_bar_close is not None else None,
            float(r.current_price) if r.current_price is not None else None,
        )
        if div is not None and div > MAX_QUOTE_DIVERGENCE:
            diverged.append(
                f"{r.symbol}  last bar close {float(r.last_bar_close):.2f} ({r.last_bar_date}) vs "
                f"stored quote {float(r.current_price):.2f} ({r.quote_date}): {div * 100:.0f}% apart"
            )

    if stale:
        return CheckResult(
            "price_history_stale", WARN,
            f"{len(stale)} active ticker(s) with a last price bar more than {MAX_STALE_SESSIONS} sessions old"
            + (f"; {len(diverged)} more diverge from the stored quote" if diverged else "")
            + (f"; {no_recent_quote} not compared (no stored quote near the last bar)" if no_recent_quote else ""),
            stale + [f"[diverged] {d}" for d in diverged],
        )
    if diverged:
        return CheckResult(
            "price_history_stale", WARN,
            f"{len(diverged)} active ticker(s) whose last bar close is more than "
            f"{int(MAX_QUOTE_DIVERGENCE * 100)}% from the stored quote",
            diverged,
        )
    note = f" ({len(unmeasured)} ok snapshots predate last_bar_date)" if unmeasured else ""
    if no_recent_quote:
        note += f" ({no_recent_quote} had no stored quote near the last bar, so closes were not compared)"
    return CheckResult(
        "price_history_stale", PASS,
        f"All {len(rows) - len(unmeasured)} measured active tickers have a price bar within "
        f"{MAX_STALE_SESSIONS} sessions and within {int(MAX_QUOTE_DIVERGENCE * 100)}% of the stored quote{note}",
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


async def check_outcome_matches_eps(session) -> CheckResult:
    """ERROR when a stored earnings outcome contradicts the row's stored eps_actual / eps_estimate.

    upsert_reaction derives outcome from the values it stores; a mismatch means
    a writer bypassed it. Repair with app.scripts.repair_outcomes --write.
    """
    rows = (await session.execute(text("""
        SELECT t.symbol, hr.event_date, hr.outcome::text AS outcome, hr.eps_actual, hr.eps_estimate
        FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
        WHERE hr.event_type = 'earnings'
          AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
          AND hr.outcome::text <> CASE WHEN hr.eps_actual > hr.eps_estimate THEN 'beat'
                                       WHEN hr.eps_actual < hr.eps_estimate THEN 'miss'
                                       ELSE 'meet' END
          AND NOT EXISTS (SELECT 1 FROM eps_basis_checks c
                          WHERE c.ticker_id = hr.ticker_id AND c.event_date = hr.event_date AND c.basis_mismatch)
        ORDER BY t.symbol, hr.event_date
    """))).all()
    if not rows:
        return CheckResult("outcome_matches_eps", PASS,
                           "Every stored earnings outcome matches its stored EPS values (basis-unclear rows excepted)")
    details = [f"{r.symbol} {r.event_date}: outcome {r.outcome}, actual {r.eps_actual} vs estimate {r.eps_estimate}"
               for r in rows]
    return CheckResult("outcome_matches_eps", ERROR,
                       f"{len(rows)} earnings row(s) have an outcome that contradicts their EPS values "
                       "(repair_outcomes --write)", details)


EPS_BASIS_SUSPECT_PCT = 100      # |surprise| beyond this, or opposite signs, suggests a basis mismatch
EPS_BASIS_SUSPECT_MIN_ROWS = 3   # tickers with this many such rows are listed


def eps_basis_suspect_result(rows: list[tuple[str, str | None, float, float]]) -> CheckResult:
    """Pure: rows are (symbol, sector, eps_actual, eps_estimate) with both values present.

    A row is suspect when actual and estimate have opposite signs, or when
    |actual - estimate| / |estimate| exceeds EPS_BASIS_SUSPECT_PCT (estimates
    under EPS_SURPRISE_DOLLAR_FLOOR are judged by sign only, as eps_surprise
    does). These rows are where Yahoo's "Reported EPS" (usually GAAP diluted,
    FFO for REITs) sits on a different basis from its "EPS Estimate" (usually
    the adjusted consensus), so the Beat/Miss label and beat rate built from
    them describe the basis gap, not the quarter.

    Planned fix: cross-check each stored eps_actual against EDGAR companyfacts
    EarningsPerShareDiluted (edgar_client.get_company_facts) and store an
    eps_basis per row (gaap / non_gaap / unknown), then label and aggregate
    only rows whose actual and estimate share a basis.
    """
    from app.thresholds import EPS_SURPRISE_DOLLAR_FLOOR

    suspect = 0
    per_ticker: dict[tuple[str, str | None], int] = {}
    for symbol, sector, actual, estimate in rows:
        opposite = actual * estimate < 0
        beyond = abs(estimate) >= EPS_SURPRISE_DOLLAR_FLOOR and abs(actual - estimate) / abs(estimate) * 100 > EPS_BASIS_SUSPECT_PCT
        if opposite or beyond:
            suspect += 1
            per_ticker[(symbol, sector)] = per_ticker.get((symbol, sector), 0) + 1
    if not suspect:
        return CheckResult("eps_basis_suspect", PASS, f"No earnings rows with a surprise beyond ±{EPS_BASIS_SUSPECT_PCT}% or opposite-sign EPS")
    listed = sorted(((sym, sec, n) for (sym, sec), n in per_ticker.items() if n >= EPS_BASIS_SUSPECT_MIN_ROWS),
                    key=lambda t: (-t[2], t[0]))
    details = [f"{sym} ({sec or 'no sector'}): {n} row(s)" for sym, sec, n in listed]
    return CheckResult("eps_basis_suspect", WARN,
                       f"{suspect} earnings row(s) across {len(per_ticker)} ticker(s) have a surprise beyond "
                       f"±{EPS_BASIS_SUSPECT_PCT}% or opposite-sign EPS (likely GAAP actual vs adjusted estimate); "
                       f"{len(listed)} ticker(s) with {EPS_BASIS_SUSPECT_MIN_ROWS}+", details)


async def check_eps_basis_suspect(session) -> CheckResult:
    """WARN on earnings rows whose EPS surprise looks like a basis mismatch (see eps_basis_suspect_result)."""
    rows = (await session.execute(text("""
        SELECT t.symbol, t.sector, hr.eps_actual, hr.eps_estimate
        FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
        WHERE hr.event_type = 'earnings' AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
    """))).all()
    return eps_basis_suspect_result([(r.symbol, r.sector, float(r.eps_actual), float(r.eps_estimate)) for r in rows])


def estimate_split_basis_result(rows: list[tuple[str, date, Decimal, Decimal, list, set]]) -> CheckResult:
    """Pure: rows are (symbol, event_date, eps_estimate, eps_actual, candidates, ticker anchors).

    ERROR when the estimate differs from the actual by a recorded split factor
    (tight band), or, once the ticker has such an anchor for a split, when a
    row before that split has its estimate nearer to factor x actual than to
    actual. upsert_reaction re-bases a frozen estimate by the same rules; a
    hit here means a row got past that or predates it. Repair with
    app.scripts.repair_outcomes --write.
    """
    from app.services.split_basis import stale_factor

    bad: list[str] = []
    checked = 0
    for symbol, event_date, estimate, actual, cands, anchors in rows:
        if not cands:
            continue
        checked += 1
        hit = stale_factor(estimate, actual, event_date, cands, anchors)
        if hit is not None:
            bad.append(f"{symbol} {event_date}: estimate {estimate} vs actual {actual} on the pre-split basis "
                       f"(factor {hit[0]:g}, split {hit[1]})")
    if bad:
        return CheckResult("estimate_split_basis", ERROR,
                           f"{len(bad)} earnings row(s) hold an estimate on a different split basis from the actual", bad)
    return CheckResult("estimate_split_basis", PASS,
                       f"{checked} earnings rows with a later split: estimate and actual on the same basis")


async def check_estimate_split_basis(session) -> CheckResult:
    """ERROR when a frozen estimate sits on a different split basis from its actual."""
    from app.services.split_basis import candidates, load_anchors, load_splits, splits_after

    rows = (await session.execute(text("""
        SELECT DISTINCT hr.ticker_id, t.symbol, hr.event_date, hr.eps_estimate, hr.eps_actual
        FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id
        JOIN events e ON e.ticker_id = hr.ticker_id AND e.event_type = 'split' AND e.event_date > hr.event_date
        WHERE hr.event_type = 'earnings' AND hr.eps_actual IS NOT NULL AND hr.eps_estimate IS NOT NULL
        ORDER BY t.symbol, hr.event_date
    """))).all()
    anchors_by_ticker: dict = {}
    out = []
    for r in rows:
        if r.ticker_id not in anchors_by_ticker:
            anchors_by_ticker[r.ticker_id] = await load_anchors(session, r.ticker_id, {})
        cands = candidates(splits_after(await load_splits(session, r.ticker_id), r.event_date))
        out.append((r.symbol, r.event_date, r.eps_estimate, r.eps_actual, cands, anchors_by_ticker[r.ticker_id]))
    return estimate_split_basis_result(out)


async def check_basis_mismatch_has_no_outcome(session) -> CheckResult:
    """ERROR when a basis-mismatch row still carries an outcome anywhere beat statistics read from.

    historical_reactions (every live beat rate, the ticker page, Discover,
    research notes) and earnings_features (the stored beat_rate and the Build
    page) must both hold no beat/miss/meet for a row eps_basis_checks flags.
    """
    live = (await session.execute(text("""
        SELECT t.symbol, hr.event_date, hr.outcome::text
        FROM eps_basis_checks c
        JOIN historical_reactions hr ON hr.ticker_id = c.ticker_id AND hr.event_date = c.event_date
                                     AND hr.event_type = 'earnings'
        JOIN tickers t ON t.id = c.ticker_id
        WHERE c.basis_mismatch AND hr.outcome <> 'unknown'
        ORDER BY 1, 2
    """))).all()
    stored = (await session.execute(text("""
        SELECT t.symbol, ef.event_date, ef.outcome
        FROM eps_basis_checks c
        JOIN earnings_features ef ON ef.ticker_id = c.ticker_id AND ef.event_date = c.event_date
        JOIN tickers t ON t.id = c.ticker_id
        WHERE c.basis_mismatch AND ef.outcome IN ('BEAT', 'MISS', 'MEET')
        ORDER BY 1, 2
    """))).all()
    flagged = await session.scalar(text("SELECT count(*) FROM eps_basis_checks WHERE basis_mismatch"))
    details = [f"{s} {d}: historical_reactions outcome {o}" for s, d, o in live]
    details += [f"{s} {d}: earnings_features outcome {o}" for s, d, o in stored]
    if details:
        return CheckResult("basis_mismatch_no_outcome", ERROR,
                           f"{len(details)} basis-mismatch row(s) still carry an outcome", details)
    return CheckResult("basis_mismatch_no_outcome", PASS,
                       f"{flagged} basis-mismatch row(s) carry no outcome in historical_reactions or earnings_features")


REFUSAL_WINDOW_DAYS = 30


async def check_refused_earnings_dates(session) -> CheckResult:
    """WARN listing tickers whose seeder refused an earnings date in the last 30 days.

    Each line shows the refused date, the blocking row, and what the blocking
    row's stored SEC acceptance time supports (refusal_evidence.support).
    Repair with app.scripts.repair_refused_dates --write (swaps only with SEC evidence).
    """
    from app.services.refusal_evidence import describe, support

    rows = (await session.execute(text("""
        SELECT t.symbol, r.refused_date, r.blocking_row_date, r.source, r.times_seen, r.last_seen,
               ert.acceptance_datetime
        FROM refused_earnings_dates r
        JOIN tickers t ON t.id = r.ticker_id
        LEFT JOIN earnings_report_timing ert ON ert.ticker_id = r.ticker_id AND ert.event_date = r.blocking_row_date
        WHERE r.last_seen >= now() - make_interval(days => :days)
        ORDER BY t.symbol, r.refused_date
    """), {"days": REFUSAL_WINDOW_DAYS})).all()
    if not rows:
        return CheckResult("refused_earnings_dates", PASS, f"No earnings dates refused by the duplicate guard in {REFUSAL_WINDOW_DAYS} days")
    details = []
    for r in rows:
        verdict = support(r.symbol, r.acceptance_datetime, r.refused_date, r.blocking_row_date)
        acc = f", 8-K accepted {r.acceptance_datetime.isoformat(timespec='minutes')}" if r.acceptance_datetime else ""
        details.append(f"{r.symbol}: {r.source} offered {r.refused_date}, refused by the {r.blocking_row_date} row "
                       f"(seen {r.times_seen}x{acc}): {describe(verdict)}")
    return CheckResult("refused_earnings_dates", WARN,
                       f"{len(rows)} earnings date(s) across {len({r.symbol for r in rows})} ticker(s) refused by the duplicate guard "
                       f"in {REFUSAL_WINDOW_DAYS} days (repair_refused_dates)", details)


async def check_cached_reads_stale(session) -> CheckResult:
    """WARN listing cached Ivy's Reads that carry a null fact while that fact is servable now.

    Same rule the options-read endpoint applies (options_read_gate.stale_facts):
    such a read is not served and the next warm regenerates it. Only reads for
    a fresh chain date count.
    """
    import json as _json
    from app.services import chain_store
    from app.services.options_read_gate import OPTIONS_READ_CACHE_VERSION, stale_facts
    from app.services.price_history_exclusion import excluded_symbols
    from app.services.rv_store import get_latest_rv_bulk

    rows = (await session.execute(text(
        "SELECT key, value FROM system_metadata WHERE key LIKE :p"
    ), {"p": f"options_read:{OPTIONS_READ_CACHE_VERSION}:%"})).all()
    reads: dict[str, dict] = {}
    for key, value in rows:
        _, _, symbol, chain_date = key.split(":", 3)
        if not chain_store.is_fresh(chain_date):
            continue
        try:
            reads[symbol] = _json.loads(value)
        except (TypeError, ValueError):
            continue
    if not reads:
        return CheckResult("cached_reads_stale", PASS, "No cached reads for a fresh chain")
    symbols = sorted(reads)
    rv_ok = await get_latest_rv_bulk(session, symbols)
    iv_ok = set((await session.execute(text("""
        SELECT DISTINCT symbol FROM iv_history
        WHERE symbol = ANY(:s) AND iv_source = 'courier' AND atm_iv IS NOT NULL AND date >= current_date - 3
    """), {"s": symbols})).scalars().all())
    excluded = await excluded_symbols(session)
    with_reactions = set((await session.execute(text("""
        SELECT DISTINCT t.symbol FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
        WHERE t.symbol = ANY(:s) AND hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL
    """), {"s": symbols})).scalars().all())
    details = []
    for sym in symbols:
        servable = {"rv": sym in rv_ok, "atm_iv": sym in iv_ok,
                    "earnings_history": sym in with_reactions and sym not in excluded}
        stale = stale_facts(reads[sym].get("fact_values"), servable)
        if stale:
            details.append(f"{sym}: {', '.join(stale)} null in the cached read while servable now")
    if details:
        return CheckResult("cached_reads_stale", WARN,
                           f"{len(details)} of {len(reads)} cached read(s) carry a null fact that is servable now "
                           "(not served; the next warm regenerates them)", details)
    return CheckResult("cached_reads_stale", PASS, f"{len(reads)} cached reads for a fresh chain, no stale facts")


async def check_analyst_stats_sessions(session) -> CheckResult:
    """ERROR when analyst stats break the session rule.

    sessions <= count always; a stored median needs >= MIN_SESSIONS distinct
    sessions; and a non-zero count with 0 sessions means the row predates the
    sessions columns and has not been recomputed.
    """
    from app.scripts.compute_analyst_reactions import MIN_SESSIONS

    rows = (await session.execute(text("""
        SELECT symbol, upgrade_count, upgrade_sessions, median_1d_upgrade,
               downgrade_count, downgrade_sessions, median_1d_downgrade
        FROM analyst_reaction_stats
    """))).all()
    bad: list[str] = []
    for r in rows:
        for side, count, sessions, median in (
            ("upgrade", r.upgrade_count, r.upgrade_sessions, r.median_1d_upgrade),
            ("downgrade", r.downgrade_count, r.downgrade_sessions, r.median_1d_downgrade),
        ):
            if sessions > count:
                bad.append(f"{r.symbol}: {side}_sessions {sessions} > {side}_count {count}")
            elif count and not sessions:
                bad.append(f"{r.symbol}: {side}_count {count} with 0 sessions (not recomputed since sessions were added)")
            elif median is not None and sessions < MIN_SESSIONS:
                bad.append(f"{r.symbol}: median_1d_{side} stored on {sessions} session(s) (< {MIN_SESSIONS})")
    if bad:
        return CheckResult("analyst_stats_sessions", ERROR, f"{len(bad)} analyst stats row(s) break the session rule", bad)
    return CheckResult("analyst_stats_sessions", PASS,
                       f"{len(rows)} analyst stats rows: sessions <= actions, medians only on >= {MIN_SESSIONS} sessions")


async def check_excluded_ticker_hidden(session) -> CheckResult:
    """Excluded tickers' reaction and stats rows stay stored and are hidden at read time.

    PASS lists how many rows are hidden per excluded ticker. ERROR when a
    stored derivation that readers cannot filter by reason (earnings_features,
    sector_peer_snapshots, magnitude_trend_snapshots) still carries an excluded
    ticker: the nightly steps must skip them.
    """
    from app.services.price_history_exclusion import excluded_symbols

    excluded = await excluded_symbols(session)
    if not excluded:
        return CheckResult("excluded_ticker_hidden", PASS, "No tickers on the price-history exclusion list")
    symbols = sorted(excluded)
    hidden = (await session.execute(text("""
        SELECT t.symbol, count(hr.id) AS reactions,
               (SELECT count(*) FROM analyst_reaction_stats a WHERE a.symbol = t.symbol) AS stats
        FROM tickers t LEFT JOIN historical_reactions hr ON hr.ticker_id = t.id
        WHERE t.symbol = ANY(:symbols) GROUP BY t.symbol ORDER BY t.symbol
    """), {"symbols": symbols})).all()
    leaked = []
    for table, col in (("earnings_features", "symbol"), ("sector_peer_snapshots", "symbol"), ("magnitude_trend_snapshots", "symbol")):
        rows = (await session.execute(text(
            f"SELECT {col}, count(*) FROM {table} WHERE {col} = ANY(:symbols) GROUP BY {col} ORDER BY {col}"
        ), {"symbols": symbols})).all()
        leaked += [f"{sym}: {n} row(s) in {table}" for sym, n in rows]
    if leaked:
        return CheckResult("excluded_ticker_hidden", ERROR,
                           f"{len(leaked)} stored derivation(s) still carry an excluded ticker", leaked)
    details = [f"{sym}: {r} reaction row(s) and {st} stats row(s) stored, hidden at read time" for sym, r, st in hidden]
    return CheckResult("excluded_ticker_hidden", PASS,
                       f"{len(symbols)} excluded ticker(s); their rows are stored and hidden: {', '.join(symbols)}", details)


async def check_rv_data_error_tickers(session) -> CheckResult:
    """WARN listing tickers whose latest rv_snapshot has status='data_error'.

    data_error means a >50% daily move with neither a volume spike nor a recorded
    split / ex-dividend on that date (rv_math): a bad adjustment or corrupt bar.
    """
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
        return CheckResult("rv_data_error_tickers", PASS, "No tickers excluded for unexplained extreme returns")

    details = [f"{r.symbol}  as_of={r.as_of_date}" for r in rows]
    return CheckResult(
        "rv_data_error_tickers", WARN,
        f"{len(rows)} ticker(s) excluded from RV (>50% daily move with no volume spike and no recorded corporate action)",
        details,
    )


def missing_snapshot_line(newest: date, missing: list[str]) -> str:
    """Pure: the line naming every active ticker with no RV snapshot on the newest snapshot date."""
    return f"{len(missing)} active ticker(s) have no RV snapshot for {newest.isoformat()}, so they leave the tape and the strip silently: " + ", ".join(missing)


async def check_rv_snapshot_coverage(session) -> CheckResult:
    """ERROR when an active ticker has no rv_snapshots row (any status) for the newest snapshot date, naming each one. A ticker that
    is not active (an index leaver) is not counted: its reason is on the ticker row (inactive_reason) and in seed_sp500's outcome."""
    newest = await session.scalar(text("SELECT max(as_of_date) FROM rv_snapshots"))
    if newest is None:
        return CheckResult("rv_snapshot_coverage", WARN, "No rv_snapshots rows at all")
    missing = list((await session.execute(text("""
        SELECT t.symbol FROM tickers t
        WHERE t.is_active AND NOT EXISTS (SELECT 1 FROM rv_snapshots r WHERE r.symbol = t.symbol AND r.as_of_date = :d)
        ORDER BY t.symbol"""), {"d": newest})).scalars().all())
    if missing:
        return CheckResult("rv_snapshot_coverage", ERROR, missing_snapshot_line(newest, missing))
    return CheckResult("rv_snapshot_coverage", PASS, f"every active ticker has an RV snapshot for {newest.isoformat()}")


async def check_chain_parity(session) -> CheckResult:
    """Every ticker whose newest chain from either source fails the put-call parity check (services/options_source), named with the
    reason; those chains are hidden from the pages (or the fallback serves). ERROR when more than 5% of the primary source's chains
    fail (a systemic fault, not a few odd quotes), WARN when any fail."""
    import json as _json
    from app.config import settings
    from app.services.options_source import PARITY_TOLERANCE_PCT
    rows = (await session.execute(text("SELECT key, value FROM system_metadata WHERE key LIKE 'chain_parity:%'"))).all()
    if not rows:
        return CheckResult("chain_parity", WARN, "No chain parity verdicts stored yet")
    fails: dict[str, list[str]] = {"courier": [], "intrinio": []}
    checked = {"courier": 0, "intrinio": 0}
    for key, raw in rows:
        sym = key.split(":", 1)[1]
        for src, v in (_json.loads(raw) or {}).items():
            checked[src] = checked.get(src, 0) + 1
            if not v.get("ok"):
                gap = f" ({v['gap_pct']:+.2f}%)" if v.get("gap_pct") is not None else ""
                fails.setdefault(src, []).append(f"{sym} {v.get('chain_date')}{gap}: {v.get('reason')}")
    primary = settings.options_primary_source
    share = len(fails.get(primary, [])) / max(checked.get(primary, 0), 1) * 100
    line = (f"put-call band limit {PARITY_TOLERANCE_PCT:g}% of the close; courier {len(fails['courier'])}/{checked['courier']} fail, "
            f"Intrinio {len(fails['intrinio'])}/{checked['intrinio']} fail; primary {primary}")
    named = [f"courier {f}" for f in fails["courier"]] + [f"Intrinio {f}" for f in fails["intrinio"]]
    level = ERROR if share > 5 else (WARN if named else PASS)
    return CheckResult("chain_parity", level, line + (": " + "; ".join(named[:30]) if named else ""), rows=named)


async def check_news_freshness(session) -> CheckResult:
    """Discover news (services/news): the newest stored story, the quote snapshot and the step's last exit. Stale or failed is an
    ERROR while DISCOVER_NEWS_ENABLED is on (the sections hide themselves, but launch depends on it) and a WARN while it is off."""
    import json as _json
    from app.config import settings
    from app.services import news as N
    from app.services.system_metadata_service import get_value
    now = datetime.now(timezone.utc)
    newest_story = await session.scalar(text("SELECT max(published_at) FROM news_stories"))
    newest_quote = await session.scalar(text("SELECT max(captured_at) FROM quote_snapshots"))
    step_exit = (_json.loads(await get_value(session, "step_outcomes") or "{}").get(N.STEP_LABEL) or {}).get("exit")
    vis = N.visibility(newest_story, step_exit, now, newest_quote)
    if vis.visible:
        hours = (now - newest_story).total_seconds() / 3600
        return CheckResult("news_freshness", PASS, f"newest story {hours:.1f}h old, quote snapshot {newest_quote:%Y-%m-%d %H:%M} UTC")
    return CheckResult("news_freshness", ERROR if settings.discover_news_enabled else WARN, f"Discover news sections hidden: {vis.reason}")


async def check_recommendations_freshness(session) -> CheckResult:
    """WARN if fewer than 300 active tickers have a recommendation fetched within recommendations.FRESH_DAYS, or any active ticker's
    newest trend is older than recommendations.MAX_AGE_DAYS (the pages hide it: Build's lean goes neutral, Discover drops the line)."""
    from app.services.recommendations import FRESH_DAYS, MAX_AGE_DAYS
    cutoff = func.now() - text(f"interval '{FRESH_DAYS} days'")
    fresh_count = await session.scalar(
        select(func.count(func.distinct(AnalystRecommendation.ticker_id)))
        .join(Ticker, Ticker.id == AnalystRecommendation.ticker_id)
        .where(Ticker.is_active.is_(True), AnalystRecommendation.fetched_at >= cutoff)
    )
    total_active = await session.scalar(
        select(func.count(Ticker.id)).where(Ticker.is_active.is_(True))
    )

    latest = (
        select(AnalystRecommendation.ticker_id, func.max(AnalystRecommendation.fetched_at).label("newest"))
        .group_by(AnalystRecommendation.ticker_id).subquery()
    )
    hidden = await session.scalar(
        select(func.count(Ticker.id)).outerjoin(latest, latest.c.ticker_id == Ticker.id)
        .where(Ticker.is_active.is_(True), (latest.c.newest.is_(None)) | (latest.c.newest < func.now() - text(f"interval '{MAX_AGE_DAYS} days'")))
    )
    line = f"{fresh_count}/{total_active} active tickers have recommendations fetched within {FRESH_DAYS} days; {hidden} older than {MAX_AGE_DAYS} days or never fetched (hidden on pages)"
    if fresh_count >= 300 and hidden == 0:
        return CheckResult("recommendations_freshness", PASS, line)
    return CheckResult("recommendations_freshness", WARN, line + ("" if fresh_count >= 300 else " (below 300 threshold)"))


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
    """ERROR listing open picks with past expiration or closed picks with null close data. A void pick is neither open nor
    closed (check_pick_void judges it): it is never expected to carry a close."""
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
            AlertPick.status == "closed",
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


VOID_PRICE_FIELDS = ("closed_at", "close_price", "option_pnl_dollars", "option_pnl_pct")     # a void pick is priced by nothing


async def check_pick_void(session) -> CheckResult:
    """ERROR listing void picks missing their reason or time, or carrying a price: a void pick keeps its void_reason and
    voided_at and is never priced (no close, no option P&L); the ledger shows it with the reason, outside every count."""
    rows = (await session.execute(text(f"""
        SELECT symbol, generated_at::date AS picked, void_reason IS NULL AS no_reason, voided_at IS NULL AS no_time,
               {", ".join(f"{c} IS NOT NULL AS has_{c}" for c in VOID_PRICE_FIELDS)}
        FROM alert_picks WHERE status = 'void'
          AND (void_reason IS NULL OR voided_at IS NULL OR {" OR ".join(f"{c} IS NOT NULL" for c in VOID_PRICE_FIELDS)})
        ORDER BY symbol, generated_at"""))).mappings().all()
    if not rows:
        n = await session.scalar(text("SELECT count(*) FROM alert_picks WHERE status = 'void'"))
        return CheckResult("pick_void", PASS, f"Every void pick ({n}) carries its reason and time and is priced by nothing")
    details = []
    for r in rows:
        problems = (["no void_reason"] if r["no_reason"] else []) + (["no voided_at"] if r["no_time"] else []) + [f"{c} set" for c in VOID_PRICE_FIELDS if r[f"has_{c}"]]
        details.append(f"{r['symbol']} picked {r['picked']}: " + ", ".join(problems))
    return CheckResult("pick_void", ERROR, f"{len(rows)} void pick(s) without a reason or time, or carrying a price", details[:40])


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
            WHERE ih.iv_source = 'courier' AND ih.current_price IS NOT NULL
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
            WHERE ih.iv_source = 'courier' AND ih.current_price IS NOT NULL AND ih.current_price > 0
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


def fresh_chain_symbols(rows, today: date | None = None) -> set[str]:
    """Pure: symbols whose newest chain date is within CHAIN_FRESH_TRADING_DAYS. `rows`: (key, chain_last_trade) of one source."""
    newest: dict[str, str] = {}
    for key, d in rows:
        parts = key.split(":")
        if len(parts) == 3 and d:
            newest[parts[1]] = max(newest.get(parts[1], ""), str(d)[:10])
    return {sym for sym, d in newest.items() if chain_store.is_fresh(d)}


async def check_chain_coverage(session) -> CheckResult:
    """Percent of active tickers with a chain from the primary source (settings.options_primary_source: the courier or
    Intrinio) no older than 2 trading days. One query: the chain dates are extracted server-side, no chain body is
    transferred."""
    from app.config import settings
    source = settings.options_primary_source
    label = CHAIN_SOURCE_LABELS.get(source, source)
    active_syms = (await session.execute(
        select(Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
    )).scalars().all()

    if not active_syms:
        return CheckResult("chain_coverage", PASS, "No active tickers")

    rows = (await session.execute(text("SELECT key, value::json->>'chain_last_trade' FROM system_metadata WHERE key LIKE :p"),
                                  {"p": f"{chain_store._PREFIX[source]}:%"})).all()
    fresh = fresh_chain_symbols(rows)
    stale = [sym for sym in active_syms if sym not in fresh]

    covered = len(active_syms) - len(stale)
    pct = covered / len(active_syms) * 100
    figures = {"chain_coverage_pct": round(pct, 1)}

    if pct >= CHAIN_COVERAGE_MIN_PCT:
        return CheckResult(
            "chain_coverage", PASS,
            f"{covered}/{len(active_syms)} active tickers ({pct:.0f}%) have a fresh {label} chain", figures=figures,
        )

    details = [f"{sym}  no fresh chain" for sym in stale]
    return CheckResult(
        "chain_coverage", ERROR,
        f"{covered}/{len(active_syms)} ({pct:.0f}%) active tickers have a fresh {label} chain (below {CHAIN_COVERAGE_MIN_PCT}%): "
        f"the {label} chains did not land",
        details, figures=figures,
    )


CHAIN_SOURCE_LABELS = {"courier": "courier", "intrinio": "Intrinio"}
CHAIN_COVERAGE_MIN_PCT = 90      # below this the options layer is failing for too many tickers to call it a quirk: ERROR, and an alert


async def check_alerting_configured(session) -> CheckResult:
    """WARN when no ntfy topic is set: failures would be silent."""
    from app.services import notify
    if notify.configured():
        return CheckResult("alerting_configured", PASS, f"ntfy alerts go to {notify.settings.ntfy_server}")
    return CheckResult("alerting_configured", WARN, "NTFY_TOPIC is not set: step failures, validate errors and the morning digest reach nobody")


async def check_iv_history_price_drift(session) -> CheckResult:
    """WARN if any iv_history row from the last 7 days drifts >20% from prior row's close (within 5 days)."""
    cutoff = date.today() - timedelta(days=7)
    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT symbol, date, current_price,
                   LAG(current_price) OVER (PARTITION BY symbol ORDER BY date) AS prev_price,
                   LAG(date) OVER (PARTITION BY symbol ORDER BY date) AS prev_date
            FROM iv_history
            WHERE iv_source = 'courier' AND current_price IS NOT NULL
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
    """ERROR if any ticker's latest stored avg abs 1d (the row the sector-peers endpoint serves) is outside [0.5, 40.0].
    Earlier rows are history: a value a later nightly replaced is not an error on the page."""
    rows = (await session.execute(text("""
        SELECT symbol, avg_abs_1d, as_of_date, quarter_count FROM (
            SELECT DISTINCT ON (symbol) symbol, avg_abs_1d, as_of_date, quarter_count FROM sector_peer_snapshots ORDER BY symbol, as_of_date DESC) latest
        WHERE avg_abs_1d IS NOT NULL AND (avg_abs_1d < 0.5 OR avg_abs_1d > 40.0) ORDER BY symbol"""))).all()

    if not rows:
        return CheckResult("sector_peer_avg_range", PASS,
                           "Every ticker's latest stored avg abs 1d is in [0.5, 40.0]")

    details = [f"{r.symbol}  avg_abs_1d={float(r.avg_abs_1d):.2f} (as of {r.as_of_date}, {r.quarter_count} reports)" for r in rows]
    return CheckResult(
        "sector_peer_avg_range", ERROR,
        f"{len(rows)} ticker(s) whose latest stored avg abs 1d is outside [0.5, 40.0]",
        details,
    )


async def check_sector_peer_sector_avg_range(session) -> CheckResult:
    """ERROR if any sector's latest stored aggregate avg abs 1d is outside [1.0, 25.0] (the latest row per sector, as served)."""
    rows = (await session.execute(text("""
        SELECT sector, sector_avg_abs_1d FROM (
            SELECT DISTINCT ON (sector) sector, sector_avg_abs_1d FROM sector_peer_snapshots ORDER BY sector, as_of_date DESC) latest
        WHERE sector_avg_abs_1d IS NOT NULL AND (sector_avg_abs_1d < 1.0 OR sector_avg_abs_1d > 25.0) ORDER BY sector"""))).all()

    if not rows:
        return CheckResult("sector_peer_sector_avg_range", PASS,
                           "Every sector's latest stored aggregate avg abs 1d is in [1.0, 25.0]")

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
    from app.services.options_read_gate import OPTIONS_READ_CACHE_VERSION

    pattern = f"options_read:{OPTIONS_READ_CACHE_VERSION}:%:{chain_date}"
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


# ── Security records: every active ticker resolves to exactly one Intrinio record per date ─────────────

async def check_security_record_coverage(session) -> CheckResult:
    """ERROR when an active ticker has no record, two records on a date, or a gap holding a session between its
    oldest stored reaction with price data and today; ERROR when a current record's last Intrinio price is more
    than STALE_SESSIONS old (the stock stopped trading or the ticker moved to a new record). Inactive tickers
    (delisted, see security_records.DELISTED) are not checked: their rows are kept and hidden at read time."""
    from app.models.security_record import SecurityRecord
    from app.services.price_bars_shadow import BENCHMARKS
    from app.services.security_records import CURRENT, Record, STALE_SESSIONS, STORED_START, coverage_problems
    from app.services.trading_calendar import sessions_after
    today = date.today()
    tickers = list((await session.execute(select(Ticker.symbol).where(Ticker.is_active.is_(True)))).scalars().all()) + list(BENCHMARKS)
    oldest = dict((await session.execute(
        select(Ticker.symbol, func.min(HistoricalReaction.event_date)).join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(Ticker.is_active.is_(True), HistoricalReaction.close_before.isnot(None)).group_by(Ticker.symbol)
    )).all())
    rows = (await session.execute(select(SecurityRecord).where(SecurityRecord.symbol.in_(list(tickers))))).scalars().all()
    by: dict[str, list[Record]] = {}
    last_price: dict[str, date | None] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(Record(r.symbol, r.intrinio_security_id, r.figi, r.composite_figi, r.name, r.valid_from, r.valid_to, r.role, r.source))
        if r.role == CURRENT:
            last_price[r.symbol] = r.last_price_date
    problems: list[str] = []
    for sym in sorted(tickers):
        start = STORED_START if sym in BENCHMARKS else (oldest.get(sym) or today)
        for p in coverage_problems(by.get(sym, []), start, today):
            problems.append(f"{sym}: {p}")
        lp = last_price.get(sym)
        if sym in by and lp is not None and sessions_after(lp, today) > STALE_SESSIONS:
            problems.append(f"{sym}: current record's last Intrinio price is {lp.isoformat()}, {sessions_after(lp, today)} sessions ago")
    if not rows:
        return CheckResult("security_record_coverage", ERROR, "No security records: run build_security_records --write")
    if problems:
        return CheckResult("security_record_coverage", ERROR, f"{len(problems)} coverage problem(s) across active tickers", problems[:60])
    return CheckResult("security_record_coverage", PASS, f"Every active ticker resolves to exactly one record per date ({len(tickers)} tickers, {len(rows)} records)")


async def check_figi_change(session) -> CheckResult:
    """ERROR when Intrinio's current FIGI for a ticker (figi_seen at the last refresh) differs from the stored one:
    the ticker now points at a different security and the record map needs a new row."""
    from app.models.security_record import SecurityRecord
    from app.services.security_records import CURRENT
    rows = (await session.execute(select(SecurityRecord).where(SecurityRecord.role == CURRENT))).scalars().all()
    changed = [f"{r.symbol}: stored FIGI {r.figi}, Intrinio now {r.figi_seen} (checked {r.checked_at.date().isoformat() if r.checked_at else '?'})"
               for r in rows if r.figi and r.figi_seen and r.figi != r.figi_seen]
    if changed:
        return CheckResult("figi_change", ERROR, f"{len(changed)} ticker(s) whose current record moved to a new FIGI", sorted(changed))
    unchecked = sum(1 for r in rows if r.figi_seen is None)
    return CheckResult("figi_change", PASS, f"No FIGI changes across {len(rows)} current records" + (f" ({unchecked} not yet refreshed)" if unchecked else ""))


# ── Splits: every stored split has its factor on the shadow bars within one session ──────────────────────

async def check_split_factor_match(session) -> CheckResult:
    """ERROR when a stored split (on or after the first stored bar) has no bar with a split factor for the symbol within
    one session, or the bar's ratio differs. Two queries; the session calendar is SPY's stored bars."""
    from app.scripts.seed_historical_reactions import REFERENCE_SYMBOL, _build_date_cache
    from app.services import price_bars
    from app.services.corporate_actions import splits_from_adjustments, unmatched_splits
    from app.services.security_records import STORED_START
    stored = [{"symbol": r.symbol, "date": r.event_date, "split_ratio": r.split_ratio} for r in (await session.execute(text("""
        select t.symbol, e.event_date, e.metadata->>'split_ratio' as split_ratio from events e join tickers t on t.id = e.ticker_id
        where e.event_type = 'split' and e.event_date >= :start and t.is_active"""), {"start": STORED_START})).all()]
    if not stored:
        return CheckResult("split_factor_match", PASS, "No stored splits inside the shadow bars' window")
    bar_rows = (await session.execute(text("select symbol, date, split_ratio, factor, dividend from price_bars_shadow where split_ratio <> 1 or (factor <> 1 and dividend = 0)"))).all()
    bar_splits = [{"symbol": r.symbol, **sp} for r in bar_rows for sp in splits_from_adjustments([r])]
    sessions = _build_date_cache(price_bars.history_sync(REFERENCE_SYMBOL, STORED_START))
    bad = unmatched_splits(stored, bar_splits, sessions)
    if bad:
        return CheckResult("split_factor_match", ERROR, f"{len(bad)} of {len(stored)} stored split(s) since {STORED_START} have no matching factor on the shadow bars", bad[:40])
    return CheckResult("split_factor_match", PASS, f"Every stored split since {STORED_START} ({len(stored)}) matches a factor on the shadow bars within one session")


# ── Reaction price sources: every row names its bars, and a ticker mixes sources only across a stored_history span ──

async def check_reaction_source_coverage(session) -> CheckResult:
    """After recompute_reactions_intrinio --write no row has price_source null. WARN while no row has one yet
    (the recompute has not run); ERROR when some rows have a source and others none."""
    rows = (await session.execute(text("SELECT coalesce(price_source, 'null') AS src, count(*) FROM historical_reactions GROUP BY 1 ORDER BY 1"))).all()
    counts = {r.src: r.count for r in rows}
    nulls = counts.get("null", 0)
    named = sum(v for k, v in counts.items() if k != "null")
    if nulls and not named:
        return CheckResult("reaction_source_coverage", WARN, f"No reaction row has a price_source yet ({nulls} rows): run recompute_reactions_intrinio --write")
    if nulls:
        return CheckResult("reaction_source_coverage", ERROR, f"{nulls} reaction row(s) with price_source null beside {named} with one", [f"{k}: {v}" for k, v in sorted(counts.items())])
    return CheckResult("reaction_source_coverage", PASS, "Every reaction row names its price source: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


async def check_reaction_source_consistency(session) -> CheckResult:
    """Within one ticker and event type the rows share one price source, except intrinio beside stored_history for a
    ticker that has a stored_history span (security_records). yfinance beside another source, or stored_history on a
    ticker without a span, is an ERROR."""
    from app.services.security_records import STORED_HISTORY_ROWS
    rows = (await session.execute(text("""
        SELECT t.symbol, hr.event_type::text AS event_type, array_agg(DISTINCT hr.price_source) AS sources
        FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
        WHERE hr.price_source IS NOT NULL GROUP BY t.symbol, hr.event_type"""))).all()
    bad, across = [], 0
    for r in rows:
        srcs = set(r.sources)
        if len(srcs) == 1 and srcs != {"stored_history"}:
            continue
        if srcs <= {"intrinio", "stored_history"} and r.symbol in STORED_HISTORY_ROWS:
            across += 1
            continue
        bad.append(f"{r.symbol} {r.event_type}: {sorted(srcs)}" + ("" if r.symbol in STORED_HISTORY_ROWS else " (no stored_history span declared)"))
    if bad:
        return CheckResult("reaction_source_consistency", ERROR, f"{len(bad)} ticker/event type(s) mixing price sources outside a stored_history span", bad[:40])
    return CheckResult("reaction_source_consistency", PASS, f"Sources consistent across {len(rows)} ticker/event type(s); {across} mix intrinio with stored_history across a declared span")


# ── IV solver: solved ATM IV against the vendor's, and the solver's own sanity band ─────────────────────

IV_VENDOR_GAP = 0.10            # |solved - vendor| above this is a gap
IV_VENDOR_GAP_SHARE = 0.05      # WARN when more than this share of the night's tickers gap
IV_VENDOR_LARGEST = 10


async def check_iv_vendor_band(session) -> CheckResult:
    """The latest solver night: WARN when more than IV_VENDOR_GAP_SHARE of tickers with a solved and a vendor ATM IV
    differ by more than IV_VENDOR_GAP. Always reports the count and the ten largest gaps with their inputs."""
    from app.models.iv_history import SOLVER_SOURCE
    night = (await session.execute(text("SELECT max(date) FROM iv_history WHERE iv_source = :src"), {"src": SOLVER_SOURCE})).scalar()
    if night is None:
        return CheckResult("iv_vendor_band", PASS, "No solver rows yet")
    rows = (await session.execute(text("""
        SELECT symbol, atm_iv, vendor_iv, solved_call_iv, solved_put_iv, vendor_call_iv, vendor_put_iv, atm_call_mid, atm_put_mid,
               current_price, atm_strike, rate, days_to_expiry, expiration, atm_iv_reason
        FROM iv_history WHERE iv_source = :src AND date = :d ORDER BY symbol
    """), {"src": SOLVER_SOURCE, "d": night})).all()
    both = [r for r in rows if r.atm_iv is not None and r.vendor_iv is not None]
    gaps = sorted(((abs(float(r.atm_iv) - float(r.vendor_iv)), r) for r in both), key=lambda x: -x[0])
    over = [g for g in gaps if g[0] > IV_VENDOR_GAP]
    share = len(over) / len(both) if both else 0.0
    detail = [f"{len(rows)} solver row(s) on {night.isoformat()}, {len(both)} with both IVs, {len(rows) - len(both)} without "
              f"({', '.join(sorted({(r.atm_iv_reason or 'no vendor IV')[:40] for r in rows if r.atm_iv is None or r.vendor_iv is None})) or 'none'})"]
    for gap, r in gaps[:IV_VENDOR_LARGEST]:
        detail.append(f"{r.symbol}: solved {float(r.atm_iv):.4f} (call {r.solved_call_iv}, put {r.solved_put_iv}) vendor {float(r.vendor_iv):.4f} "
                      f"(call {r.vendor_call_iv}, put {r.vendor_put_iv}) gap {gap:.4f}; mids {r.atm_call_mid}/{r.atm_put_mid}, spot {r.current_price}, "
                      f"strike {r.atm_strike}, rate {r.rate}, days {r.days_to_expiry}, expiry {r.expiration}")
    msg = f"{len(over)}/{len(both)} ticker(s) ({share * 100:.1f}%) differ from the vendor by more than {IV_VENDOR_GAP} on {night.isoformat()}"
    return CheckResult("iv_vendor_band", WARN if share > IV_VENDOR_GAP_SHARE else PASS, msg, detail)


async def check_iv_solver_band(session) -> CheckResult:
    """ERROR on any solved IV (either side or the ATM mean) outside [IV_SANITY_MIN, IV_SANITY_MAX]."""
    from app.models.iv_history import SOLVER_SOURCE
    from app.services.iv_solver import IV_SANITY_MAX, IV_SANITY_MIN
    rows = (await session.execute(text("""
        SELECT symbol, date, atm_iv, solved_call_iv, solved_put_iv FROM iv_history
        WHERE iv_source = :src AND (
            (atm_iv IS NOT NULL AND (atm_iv < :lo OR atm_iv > :hi)) OR
            (solved_call_iv IS NOT NULL AND (solved_call_iv < :lo OR solved_call_iv > :hi)) OR
            (solved_put_iv IS NOT NULL AND (solved_put_iv < :lo OR solved_put_iv > :hi)))
        ORDER BY date DESC, symbol
    """), {"src": SOLVER_SOURCE, "lo": IV_SANITY_MIN, "hi": IV_SANITY_MAX})).all()
    if rows:
        return CheckResult("iv_solver_band", ERROR, f"{len(rows)} solver row(s) with an IV outside [{IV_SANITY_MIN}, {IV_SANITY_MAX}]",
                           [f"{r.symbol} {r.date}: atm {r.atm_iv} call {r.solved_call_iv} put {r.solved_put_iv}" for r in rows[:30]])
    n = (await session.execute(text("SELECT count(*) FROM iv_history WHERE iv_source = :src"), {"src": SOLVER_SOURCE})).scalar()
    return CheckResult("iv_solver_band", PASS, f"Every solved IV within [{IV_SANITY_MIN}, {IV_SANITY_MAX}] ({n} solver rows)")


# ── As-of dates: every source a page dates itself by is on or before today ──────────────────────────────

async def check_as_of_not_future(session) -> CheckResult:
    """ERROR when any stored row a page may show as an as-of date is dated after today: bars, RV snapshots, chains,
    profiles, share counts, reactions, the calendar's checked_at and dividend amounts' stored_on. An as-of is when we knew."""
    probes = {
        "price_bars_shadow.date": "SELECT count(*) FROM price_bars_shadow WHERE date > CURRENT_DATE",
        "rv_snapshots.as_of_date": "SELECT count(*) FROM rv_snapshots WHERE as_of_date > CURRENT_DATE",
        "historical_reactions.event_date": "SELECT count(*) FROM historical_reactions WHERE event_date > CURRENT_DATE",
        "company_profiles.fetched_at": "SELECT count(*) FROM company_profiles WHERE fetched_at > now()",
        "tickers.shares_as_of": "SELECT count(*) FROM tickers WHERE shares_as_of > now()",
        "events.checked_at": "SELECT count(*) FROM events WHERE checked_at > now()",
        "events.updated_at": "SELECT count(*) FROM events WHERE updated_at > now() + interval '1 minute'",
        "events.declared_on": "SELECT count(*) FROM events WHERE (metadata->>'declared_on')::date > CURRENT_DATE",
        "chain_last_trade": """SELECT count(*) FROM system_metadata WHERE key LIKE 'chain:%' AND key NOT LIKE 'chain:%:%:%'
                               AND substring(value from '"chain_last_trade": ?"([0-9]{4}-[0-9]{2}-[0-9]{2})')::date > CURRENT_DATE""",
    }
    bad = []
    for name, sql in probes.items():
        n = (await session.execute(text(sql))).scalar() or 0
        if n:
            bad.append(f"{name}: {n} row(s) dated after today")
    if bad:
        return CheckResult("as_of_not_future", ERROR, f"{len(bad)} as-of source(s) carry a future date", bad)
    return CheckResult("as_of_not_future", PASS, f"No as-of source is dated after today ({len(probes)} sources checked)")


# ── Trailing P/E: a stored P/E rests on a window that holds the latest reported quarter; release figures are checked ──

RELEASE_CHECK_DUE_DAYS = 75     # a 10-Q is due within 40 days of the quarter, a 10-K within 60 to 90: after this many days an unchecked release figure is late


async def check_pe_window_fresh(session) -> CheckResult:
    """ERROR when a ticker's latest stored P/E (status ok or not meaningful) rests on a window computed for an older report than
    the ticker's latest reported quarter (a confirmed or EPS-bearing earnings event, or a reaction row, dated on or before today)."""
    rows = (await session.execute(text("""
        WITH latest AS (SELECT DISTINCT ON (symbol) symbol, as_of_date, status, latest_report, window_end FROM pe_snapshots ORDER BY symbol, as_of_date DESC),
        reports AS (
            SELECT symbol, max(d) AS d FROM (
                SELECT t.symbol, e.event_date AS d FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE e.event_type = 'earnings' AND e.event_date <= CURRENT_DATE AND (e.is_confirmed OR e.eps_actual IS NOT NULL)
                UNION ALL
                SELECT t.symbol, hr.event_date FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id WHERE hr.event_type = 'earnings' AND hr.event_date <= CURRENT_DATE) x GROUP BY symbol)
        SELECT l.symbol, l.as_of_date, l.latest_report, r.d FROM latest l JOIN reports r ON r.symbol = l.symbol
        WHERE l.status IN ('ok', 'not_meaningful', 'not_meaningful_yet') AND (l.latest_report IS NULL OR r.d > l.latest_report) ORDER BY l.symbol"""))).all()
    if rows:
        return CheckResult("pe_window_fresh", ERROR, f"{len(rows)} stored P/E(s) rest on a window computed before the latest reported quarter",
                           [f"{sym}: P/E of {d} computed for the report of {lr}; latest report {rep}" for sym, d, lr, rep in rows[:10]])
    n = (await session.execute(text("SELECT count(DISTINCT symbol) FROM pe_snapshots WHERE status IN ('ok', 'not_meaningful', 'not_meaningful_yet')"))).scalar() or 0
    return CheckResult("pe_window_fresh", PASS, f"Every stored P/E ({n} tickers) rests on a window that holds the latest reported quarter")


async def check_release_eps_checked(session) -> CheckResult:
    """ERROR when a release figure differs from the XBRL figure for the same quarter by more than the tolerance (release_eps.flagged);
    WARN when a release figure older than RELEASE_CHECK_DUE_DAYS has still not been checked against XBRL."""
    flagged = (await session.execute(text("SELECT symbol, report_date, diluted_eps_gaap, xbrl_eps FROM release_eps WHERE flagged ORDER BY report_date DESC"))).all()
    if flagged:
        return CheckResult("release_eps_checked", ERROR, f"{len(flagged)} release EPS figure(s) differ from XBRL",
                           [f"{s}: {d} release {float(r):+.2f} vs XBRL {float(x):+.2f}" for s, d, r, x in flagged[:10]])
    late = (await session.execute(text("SELECT symbol, report_date FROM release_eps WHERE xbrl_checked_at IS NULL AND report_date < CURRENT_DATE - :n * interval '1 day' ORDER BY report_date"),
                                  {"n": RELEASE_CHECK_DUE_DAYS})).all()
    total = (await session.execute(text("SELECT count(*), count(xbrl_eps), count(*) FILTER (WHERE xbrl_note IS NOT NULL) FROM release_eps"))).one()
    if late:
        return CheckResult("release_eps_checked", WARN, f"{len(late)} release EPS figure(s) older than {RELEASE_CHECK_DUE_DAYS} days await their XBRL check",
                           [f"{s}: report of {d}" for s, d in late[:10]])
    return CheckResult("release_eps_checked", PASS, f"Release EPS figures: {total[0]} stored, {total[1]} checked against a directly reported XBRL quarter, "
                       f"{total[2]} not comparable (XBRL holds the quarter only as a derived figure), none flagged, none overdue")


PE_MIN_SANE = 2.0                 # no S&P 500 company trades under twice its trailing earnings: a lower P/E is a basis error (BKNG's 0.94 was post-split price over pre-split earnings)
PE_HIGH_NOTE = 300.0              # a P/E above this is real but rests on tiny earnings; listed for a look


async def check_pe_sanity(session) -> CheckResult:
    """ERROR when a latest ok P/E snapshot is under PE_MIN_SANE or was computed by an older version than valuation.PE_COMPUTATION_VERSION;
    WARN listing those above PE_HIGH_NOTE."""
    from app.services.valuation import PE_COMPUTATION_VERSION
    rows = (await session.execute(text("""
        SELECT symbol, pe, price, trailing_eps, computation_version FROM (
            SELECT DISTINCT ON (symbol) symbol, status, pe, price, trailing_eps, computation_version FROM pe_snapshots ORDER BY symbol, as_of_date DESC) latest
        WHERE status = 'ok' AND pe IS NOT NULL ORDER BY pe"""))).all()
    low = [f"{r.symbol}: P/E {float(r.pe):.2f} (price {float(r.price):.2f} over trailing EPS {float(r.trailing_eps):.2f})" for r in rows if float(r.pe) < PE_MIN_SANE]
    stale = [f"{r.symbol}: computed by version {r.computation_version}, current is {PE_COMPUTATION_VERSION}" for r in rows if (r.computation_version or 1) < PE_COMPUTATION_VERSION]
    if low or stale:
        return CheckResult("pe_sanity", ERROR, f"{len(low)} P/E value(s) under {PE_MIN_SANE:g} and {len(stale)} computed by an older version", low[:20] + stale[:20])
    high = [f"{r.symbol}: P/E {float(r.pe):.0f} on trailing EPS {float(r.trailing_eps):.2f}" for r in rows if float(r.pe) > PE_HIGH_NOTE]
    if high:
        return CheckResult("pe_sanity", WARN, f"{len(high)} P/E value(s) above {PE_HIGH_NOTE:g}, resting on tiny earnings", high[:40])
    return CheckResult("pe_sanity", PASS, f"Every shown P/E ({len(rows)}) is at least {PE_MIN_SANE:g}, at most {PE_HIGH_NOTE:g}, and computed by version {PE_COMPUTATION_VERSION}")


EPS_OUTLIER_SHARE = 0.10          # a quarter under this share of its neighbours' average, all positive, is listed for a look
EPS_OUTLIER_YEARS = 6             # the P/E history reads five years of quarters; one more for the year-ago comparisons


async def check_eps_quarter_outliers(session) -> CheckResult:
    """WARN listing stored quarters under EPS_OUTLIER_SHARE of the average of their two neighbours when all three are positive, in the
    last EPS_OUTLIER_YEARS years. Some are real (ABBV's 0.03 for Q4 2017, a tax charge); a run of identical values across tickers
    (0.05 for 2025-09-30, 0.33 for 2026-03-31) is another filer's quarter merged in, which compute_pe --reread --write removes."""
    rows = (await session.execute(text("""
        WITH q AS (SELECT symbol, period_end, eps, lag(eps) OVER (PARTITION BY symbol ORDER BY period_end) AS prev,
                          lead(eps) OVER (PARTITION BY symbol ORDER BY period_end) AS nxt FROM eps_quarters)
        SELECT symbol, period_end, eps, prev, nxt FROM q
        WHERE eps >= 0 AND prev > 0 AND nxt > 0 AND eps < :share * (prev + nxt) / 2 AND period_end >= CURRENT_DATE - :years * interval '1 year'
        ORDER BY period_end DESC, symbol"""), {"share": EPS_OUTLIER_SHARE, "years": EPS_OUTLIER_YEARS})).all()
    if rows:
        return CheckResult("eps_quarter_outliers", WARN, f"{len(rows)} stored quarter(s) under {EPS_OUTLIER_SHARE:.0%} of their neighbours' average with no loss",
                           [f"{r.symbol} {r.period_end}: {float(r.eps):+.2f} between {float(r.prev):+.2f} and {float(r.nxt):+.2f}" for r in rows[:60]])
    return CheckResult("eps_quarter_outliers", PASS, f"No stored quarter in the last {EPS_OUTLIER_YEARS} years sits under {EPS_OUTLIER_SHARE:.0%} of its neighbours' average without a loss")


async def check_share_count_jumps(session) -> CheckResult:
    """WARN when a ticker's weighted-average diluted share count moves more than SHARE_JUMP_PCT between consecutive stored quarters with no
    corporate action or split recorded between them (a spin-off, merger, share-exchange acquisition or rename-merge the P/E rule should know about)."""
    from app.services.valuation import SHARE_JUMP_PCT, share_jumps, split_ratio
    rows = (await session.execute(text("SELECT symbol, period_end, period_start, diluted_shares FROM eps_quarters WHERE diluted_shares IS NOT NULL AND period_end >= CURRENT_DATE - interval '2 years' ORDER BY symbol, period_end"))).all()
    actions: dict[str, list] = {}
    # a recorded action between the quarters explains the change; so does a recorded split whose ratio matches it (a split restates earlier quarters in later filings)
    for sym, d in (await session.execute(text("""SELECT t.symbol, e.event_date FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata ? 'corporate_action')
            UNION ALL SELECT symbol, renamed_on FROM ticker_aliases"""))).all():
        actions.setdefault(sym, []).append(d)
    splits: dict[str, list] = {}
    for sym, d, ratio in (await session.execute(text("""SELECT t.symbol, e.event_date, e.metadata->>'split_ratio' FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE e.event_type = 'split'"""))).all():
        splits.setdefault(sym, []).append((d, split_ratio(ratio)))
    by_symbol: dict[str, list[dict]] = {}
    for sym, end, start, shares in rows:
        by_symbol.setdefault(sym, []).append({"end": end, "start": start, "diluted_shares": float(shares)})
    flagged = []
    for sym, qs in by_symbol.items():
        for j in share_jumps(qs, actions.get(sym, []), splits.get(sym, [])):
            flagged.append(f"{sym}: diluted shares {j['from_shares']:,.0f} ({j['from_end']}) to {j['to_shares']:,.0f} ({j['to_end']}), {j['change_pct']:+.1f}%, no recorded action")
    if flagged:
        return CheckResult("share_count_jumps", WARN, f"{len(flagged)} quarter-to-quarter share count change(s) over {SHARE_JUMP_PCT}% with no recorded corporate action", flagged[:12])
    return CheckResult("share_count_jumps", PASS, f"No diluted share count moved more than {SHARE_JUMP_PCT}% between quarters without a recorded action or matching split ({len(by_symbol)} tickers, two years)")


# ── Dividends: the next amount is a per-payment figure in line with the last one paid ─────────────────

NEXT_DIVIDEND_TOLERANCE_PCT = 10

async def check_next_dividend_amount(session) -> CheckResult:
    """ERROR when a stored upcoming ex-dividend amount carries no per-payment basis (seed_dividends.PER_PAYMENT_BASES: the bars'
    cash per share, the last payment on the bars, or yfinance's last declared payment), or is more than NEXT_DIVIDEND_TOLERANCE_PCT
    off the last dividend Intrinio recorded on the bars, unless the event's metadata carries a declaration (declared: true).
    Catches an annual rate stored as a payment by any writer, whether or not the bars hold a payment to compare it with."""
    from app.scripts.seed_dividends import PER_PAYMENT_BASES
    rows = (await session.execute(text("""
        SELECT t.symbol, e.event_date, (e.metadata->>'dividend_amount')::float AS amount, e.metadata->>'basis' AS basis,
               (SELECT dividend FROM price_bars_shadow b WHERE b.symbol = t.symbol AND b.dividend > 0 ORDER BY b.date DESC LIMIT 1) AS last_paid
        FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE e.event_type = 'ex_dividend' AND e.event_date >= CURRENT_DATE AND t.is_active AND COALESCE(e.metadata->>'declared', 'false') <> 'true'
        ORDER BY e.event_date, t.symbol"""))).all()
    bad = []
    for r in rows:
        if r.amount is None:
            continue
        if r.basis not in PER_PAYMENT_BASES:
            bad.append(f"{r.symbol} {r.event_date.isoformat()}: stored {r.amount} with no per-payment basis ({r.basis or 'no basis'})"
                       + (f" vs last paid {float(r.last_paid)}" if r.last_paid is not None else ""))
            continue
        if r.last_paid is None:
            continue
        if abs(r.amount - float(r.last_paid)) > float(r.last_paid) * NEXT_DIVIDEND_TOLERANCE_PCT / 100:
            bad.append(f"{r.symbol} {r.event_date.isoformat()}: stored {r.amount} ({r.basis}) vs last paid {float(r.last_paid)}")
    if bad:
        return CheckResult("next_dividend_amount", ERROR, f"{len(bad)} upcoming dividend amount(s) without a per-payment basis or more than {NEXT_DIVIDEND_TOLERANCE_PCT}% off the last paid", bad[:40])
    return CheckResult("next_dividend_amount", PASS, f"Every stored upcoming dividend carries a per-payment basis and is within {NEXT_DIVIDEND_TOLERANCE_PCT}% of the last paid ({len(rows)} checked)")


# ── The calendar: a company-confirmed date stands alone; a past estimate never stands as resolved ───────

ESTIMATE_BESIDE_CONFIRMED_DAYS = 45

async def check_estimate_beside_confirmed(session) -> CheckResult:
    """ERROR when a ticker holds an unconfirmed future estimate within ESTIMATE_BESIDE_CONFIRMED_DAYS of a company-confirmed
    future date: the confirmed date replaces the estimate (refresh_earnings_calendar), it never sits beside it."""
    rows = (await session.execute(text("""
        SELECT t.symbol, est.event_date, con.event_date FROM events est
        JOIN events con ON con.ticker_id = est.ticker_id AND con.event_type = 'earnings' AND con.is_confirmed AND con.event_date >= CURRENT_DATE
        JOIN tickers t ON t.id = est.ticker_id
        WHERE est.event_type = 'earnings' AND NOT est.is_confirmed AND est.event_date >= CURRENT_DATE
          AND abs(est.event_date - con.event_date) <= :d AND t.is_active ORDER BY t.symbol"""), {"d": ESTIMATE_BESIDE_CONFIRMED_DAYS})).all()
    if rows:
        return CheckResult("estimate_beside_confirmed", ERROR, f"{len(rows)} estimate(s) stand beside a company-confirmed date",
                           [f"{r[0]}: estimate {r[1].isoformat()} beside confirmed {r[2].isoformat()}" for r in rows[:40]])
    return CheckResult("estimate_beside_confirmed", PASS, f"No estimate within {ESTIMATE_BESIDE_CONFIRMED_DAYS} days of a company-confirmed date")


async def check_past_estimate_standing(session) -> CheckResult:
    """ERROR when an unconfirmed estimate two or more sessions in the past still stands as a resolved date: no reported
    EPS, no reaction row, and not marked unresolved. The calendar step marks every such row the night it ages past."""
    from app.services.trading_calendar import sessions_after
    today = date.today()
    rows = (await session.execute(text("""
        SELECT t.symbol, e.event_date, e.source::text FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE e.event_type = 'earnings' AND NOT e.is_confirmed AND e.unresolved_since IS NULL AND e.eps_actual IS NULL
          AND e.event_date < CURRENT_DATE AND t.is_active
          AND NOT EXISTS (SELECT 1 FROM historical_reactions hr WHERE hr.ticker_id = e.ticker_id AND hr.event_type = 'earnings'
                          AND hr.event_date BETWEEN e.event_date - 3 AND e.event_date + 3)
        ORDER BY e.event_date DESC, t.symbol"""))).all()
    stale = [f"{r[0]} {r[1].isoformat()} ({r[2]})" for r in rows if sessions_after(r[1], today) >= 2]
    if stale:
        return CheckResult("past_estimate_standing", ERROR, f"{len(stale)} past estimate(s) still stand as resolved dates", stale[:40])
    return CheckResult("past_estimate_standing", PASS, "No past estimate stands as a resolved date")


# ── Prices behind every reaction; a realized-volatility snapshot that was really computed ─────────────

async def check_reactions_after_first_bar(session) -> CheckResult:
    """ERROR when a ticker carries a reaction dated before its record's first stored bar (nothing priced it); rows on a
    declared stored-history span are exempt. A renamed ticker is where this bites: the merge now refuses such rows."""
    rows = (await session.execute(text("""
        SELECT t.symbol, hr.event_type::text, hr.event_date, fb.first_bar FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id
        JOIN (SELECT symbol, min(date) AS first_bar FROM price_bars_shadow GROUP BY symbol) fb ON fb.symbol = t.symbol
        WHERE hr.event_date < fb.first_bar AND COALESCE(hr.price_source, '') <> 'stored_history' ORDER BY t.symbol, hr.event_date"""))).all()
    if rows:
        return CheckResult("reactions_after_first_bar", ERROR, f"{len(rows)} reaction(s) dated before the ticker's first stored bar",
                           [f"{r[0]} {r[1]} {r[2].isoformat()} (first bar {r[3].isoformat()})" for r in rows[:40]])
    return CheckResult("reactions_after_first_bar", PASS, "Every reaction is dated on or after its ticker's first stored bar (stored-history spans exempt)")


async def check_rv_snapshot_unchanged(session) -> CheckResult:
    """WARN when a ticker's rv_20d is identical to the previous snapshot's to six decimals (last 10 days, status ok):
    a value carried forward or computed from the same bars twice, not a fresh measurement."""
    rows = (await session.execute(text("""
        WITH r AS (SELECT symbol, as_of_date, rv_20d, status,
                          lag(rv_20d) OVER (PARTITION BY symbol ORDER BY as_of_date) AS prev_rv,
                          lag(as_of_date) OVER (PARTITION BY symbol ORDER BY as_of_date) AS prev_date
                   FROM rv_snapshots WHERE as_of_date >= CURRENT_DATE - 14)
        SELECT symbol, as_of_date, prev_date, rv_20d FROM r
        WHERE as_of_date >= CURRENT_DATE - 10 AND status = 'ok' AND rv_20d IS NOT NULL AND round(rv_20d, 6) = round(prev_rv, 6)
        ORDER BY as_of_date DESC, symbol"""))).all()
    if rows:
        return CheckResult("rv_snapshot_unchanged", WARN, f"{len(rows)} realized-volatility snapshot(s) identical to the previous day's",
                           [f"{r[0]} {r[1].isoformat()} = {r[2].isoformat()}: rv_20d {r[3]}" for r in rows[:40]])
    return CheckResult("rv_snapshot_unchanged", PASS, "No realized-volatility snapshot in the last 10 days repeats the previous day's value")


# ── One earnings event per ticker and date ────────────────────────────────────────────────────────────

async def check_earnings_events_unique(session) -> CheckResult:
    """ERROR when a ticker has two events of one type on one date (analyst actions exempt), or when the unique index that
    prevents it is missing (scripts/dedupe_earnings_events --write)."""
    from app.scripts.dedupe_earnings_events import INDEX_NAME
    dups = (await session.execute(text("""
        SELECT t.symbol, e.event_type::text, e.event_date, count(*) FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE e.event_type <> 'analyst_action' GROUP BY t.symbol, e.event_type, e.event_date HAVING count(*) > 1 ORDER BY 3 DESC, 1"""))).all()
    has_index = (await session.execute(text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": INDEX_NAME})).scalar()
    rows = [f"{r[0]} {r[1]} {r[2].isoformat()}: {r[3]} rows" for r in dups]
    if not has_index:
        rows.append(f"unique index {INDEX_NAME} is missing (run dedupe_earnings_events --write)")
    if rows:
        return CheckResult("earnings_events_unique", ERROR, f"{len(dups)} event(s) stored twice" + ("" if has_index else "; no unique index"), rows[:40])
    return CheckResult("earnings_events_unique", PASS, f"One event per ticker, type and date (analyst actions exempt), enforced by {INDEX_NAME}")


# ── EPS actuals arrive the night of the report ─────────────────────────────────────────────────────────

async def check_eps_actuals_fresh(session) -> CheckResult:
    """WARN for any earnings event of an active ticker in the last 30 days that is older than two sessions and has no
    EPS actual on the event (scripts/seed_eps_actuals)."""
    from app.services.eps_actuals import STALE_SESSIONS, is_stale
    today = date.today()
    rows = (await session.execute(text("""
        SELECT t.symbol, e.event_date, e.eps_actual FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE e.event_type = 'earnings' AND t.is_active AND e.event_date <= :today AND e.event_date >= :since ORDER BY e.event_date, t.symbol"""),
        {"today": today, "since": today - timedelta(days=30)})).all()
    stale = [f"{r.symbol} reported {r.event_date.isoformat()}" for r in rows if is_stale(r.event_date, today, r.eps_actual)]
    if stale:
        return CheckResult("eps_actuals_fresh", WARN, f"{len(stale)} reported event(s) older than {STALE_SESSIONS} sessions have no EPS actual", stale[:40])
    return CheckResult("eps_actuals_fresh", PASS, f"Every reported event older than {STALE_SESSIONS} sessions in the last 30 days has its EPS actual ({len(rows)} checked)")


# ── Identity: the symbol is Intrinio's, nothing half-delisted stays active, pending repairs are named ──────

async def check_symbol_matches_record(session) -> CheckResult:
    """ERROR when an active ticker's symbol differs from its current record's intrinio_ticker (Intrinio's dot for a
    share class read as the app's hyphen): Intrinio renamed the security and the records build has not followed
    (it does, on its next write)."""
    rows = (await session.execute(text("""
        SELECT t.symbol, sr.intrinio_ticker, sr.intrinio_security_id FROM tickers t
        JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current'
        WHERE t.is_active AND sr.intrinio_ticker IS NOT NULL AND replace(upper(sr.intrinio_ticker), '.', '-') <> t.symbol ORDER BY t.symbol"""))).all()
    if rows:
        return CheckResult("symbol_matches_record", ERROR, f"{len(rows)} active ticker(s) whose symbol differs from Intrinio's",
                           [f"{r.symbol}: Intrinio record {r.intrinio_security_id} trades as {r.intrinio_ticker}" for r in rows])
    n = (await session.execute(text("SELECT count(*) FROM tickers t JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current' WHERE t.is_active"))).scalar()
    return CheckResult("symbol_matches_record", PASS, f"Every active ticker's symbol is its Intrinio record's ticker ({n} checked)")


async def check_delisting_signals(session) -> CheckResult:
    """ERROR on any active ticker showing two of the three delisting signals (stale Intrinio price, Intrinio inactive,
    absent from the constituent list); the nightly delists only on all three (build_security_records)."""
    from app.scripts.build_security_records import delisting_signals
    rows = (await session.execute(text("""
        SELECT t.symbol, t.index_member, sr.last_price_date, sr.intrinio_active FROM tickers t
        JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current' WHERE t.is_active ORDER BY t.symbol"""))).all()
    today = date.today()
    bad = []
    for r in rows:
        signals = delisting_signals(r.last_price_date, r.intrinio_active, r.index_member, today)
        if len(signals) >= 2:
            bad.append(f"{r.symbol}: " + "; ".join(signals))
    if bad:
        return CheckResult("delisting_signals", ERROR, f"{len(bad)} active ticker(s) show two or more delisting signals", bad[:40])
    return CheckResult("delisting_signals", PASS, f"No active ticker shows two delisting signals ({len(rows)} checked)")


PENDING_REPAIRS = (
    # (check that states the precondition, levels that mean the repair is pending, the command)
    ("fomc_dates_official", (ERROR,), "python -m app.scripts.repair_fomc_dates --write"),
    ("fomc_events_unique", (ERROR,), "python -m app.scripts.repair_fomc_dates --write"),
    ("duplicate_earnings_reactions", (ERROR, WARN), "python -m app.scripts.dedupe_earnings_reactions --write"),
    ("refused_earnings_dates", (ERROR,), "python -m app.scripts.repair_refused_dates --write"),
    ("earnings_events_unique", (ERROR,), "python -m app.scripts.dedupe_earnings_events --write"),
)


async def check_pending_repairs(session) -> CheckResult:
    """WARN naming each one-off repair whose precondition holds tonight, with the command. Reads the other checks'
    verdicts (PENDING_REPAIRS) rather than re-deciding them."""
    by_name = {c.__name__.replace("check_", ""): c for c in CHECKS}
    pending = []
    for name, levels, command in PENDING_REPAIRS:
        fn = by_name.get(name)
        if fn is None:
            continue
        r = (await run_checks([fn]))[0]
        if r.level in levels:
            pending.append(f"{command}  ({name}: {r.message[:100]})")
    if pending:
        return CheckResult("pending_repairs", WARN, f"{len(pending)} one-off repair(s) have their precondition tonight", sorted(set(pending)))
    return CheckResult("pending_repairs", PASS, "No one-off repair has its precondition tonight")


# ── Chain shadow: Intrinio's EOD chain against the courier's, night by night ──────────────────────────

async def check_chain_shadow(session) -> CheckResult:
    """Judges the stored shadow nights (chain_shadow:{date}, written by the Options chains step as it stores each
    night's Intrinio chains and compares the front expiry with the courier's). One query. WARN until MIN_NIGHTS nights
    exist, then ERROR unless the last MIN_NIGHTS all pass the retirement criteria."""
    import json as _json
    from app.services.chain_shadow import MIN_NIGHTS, evaluate
    raws = (await session.execute(select(SystemMetadata.value).where(SystemMetadata.key.like("chain_shadow:%")))).scalars().all()
    nights = []
    for raw in raws:
        try:
            nights.append(_json.loads(raw)["totals"])
        except (ValueError, KeyError, TypeError):
            continue
    v = evaluate(nights, MIN_NIGHTS)
    level = {"pass": PASS, "warn": WARN, "error": ERROR}[v.level]
    return CheckResult("chain_shadow", level, v.message, v.rows)


# ── FOMC decision days: the module, the page and the rows agree ───────────────

async def check_fomc_dates_official(session) -> CheckResult:
    """ERROR if any "FOMC Meeting" event or any fomc reaction row sits on a day that is not an official decision day."""
    from app.services.fomc_calendar import FOMC_EVENT_TITLE, is_decision_day
    event_days = (await session.execute(
        select(Event.event_date, func.count()).where(Event.ticker_id.is_(None), Event.title == FOMC_EVENT_TITLE).group_by(Event.event_date)
    )).all()
    reaction_days = (await session.execute(
        select(HistoricalReaction.event_date, func.count()).where(HistoricalReaction.event_type == EventType.FOMC).group_by(HistoricalReaction.event_date)
    )).all()
    bad = [f"event {d.isoformat()} ({n} row{'s' if n != 1 else ''})" for d, n in event_days if not is_decision_day(d)]
    bad += [f"reactions {d.isoformat()} ({n} rows)" for d, n in reaction_days if not is_decision_day(d)]
    if bad:
        return CheckResult("fomc_dates_official", ERROR,
                           f"{len(bad)} FOMC date(s) that are not official decision days (run repair_fomc_dates)", sorted(bad))
    return CheckResult("fomc_dates_official", PASS, f"Every FOMC event and reaction date is an official decision day ({len(event_days)} event dates)")


async def check_fomc_events_unique(session) -> CheckResult:
    """ERROR if two "FOMC Meeting" events fall within MEETING_GAP_DAYS of each other: one meeting written twice."""
    from app.services.fomc_calendar import FOMC_EVENT_TITLE, MEETING_GAP_DAYS
    days = sorted((await session.execute(
        select(Event.event_date).where(Event.ticker_id.is_(None), Event.title == FOMC_EVENT_TITLE)
    )).scalars().all())
    pairs = [f"{a.isoformat()} and {b.isoformat()}" for a, b in zip(days, days[1:]) if (b - a).days < MEETING_GAP_DAYS]
    if pairs:
        return CheckResult("fomc_events_unique", ERROR, f"{len(pairs)} pair(s) of FOMC events within {MEETING_GAP_DAYS} days", pairs)
    return CheckResult("fomc_events_unique", PASS, f"No two FOMC events within {MEETING_GAP_DAYS} days ({len(days)} events)")


async def check_fomc_calendar_matches_fed(session) -> CheckResult:
    """ERROR when the Fed's page disagrees with fomc_calendar.py on any past day or the next 12 months;
    WARN when the page cannot be fetched or the module has no dates for next year."""
    import httpx
    from app.services.fomc_calendar import FED_CALENDAR_URL, disagreements, next_year_covered, parse_fed_calendar
    today = date.today()
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0 (alert-interface validate)"}) as client:
            resp = await client.get(FED_CALENDAR_URL)
            resp.raise_for_status()
        page = parse_fed_calendar(resp.text)
    except Exception as exc:
        return CheckResult("fomc_calendar_matches_fed", WARN, f"Fed calendar page could not be fetched or read: {redact(exc)}")
    if not page:
        return CheckResult("fomc_calendar_matches_fed", WARN, "Fed calendar page fetched but no meetings were parsed")
    diffs = disagreements(page, today)
    if diffs:
        return CheckResult("fomc_calendar_matches_fed", ERROR,
                           f"{len(diffs)} FOMC date(s) differ between the Fed page and fomc_calendar.py", diffs)
    if not next_year_covered(today):
        return CheckResult("fomc_calendar_matches_fed", WARN, f"fomc_calendar.py has no decision days for {today.year + 1}")
    years = ", ".join(str(y) for y in sorted(page))
    return CheckResult("fomc_calendar_matches_fed", PASS, f"Fed page and fomc_calendar.py agree on every decision day through {today.year + 1} (page years {years})")


# ── FOMC pre-listing guard ────────────────────────────────────────────────────

async def check_fomc_before_first_bar(session) -> CheckResult:
    """ERROR when a FOMC reaction carries a move dated before the ticker's first stored bar: the company's own
    history begins at that bar (a recycled symbol, a merger), so an earlier move is another company's. A row on a
    declared stored_history span (security_records) is that company's own history kept from yfinance and is exempt.
    One query; this replaces the hand-typed listing overrides."""
    rows = (await session.execute(text("""
        SELECT t.symbol, hr.event_date, b.first_bar, hr.pct_change_1d, hr.pct_change_3d, hr.pct_change_5d
        FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id
        JOIN (SELECT symbol, min(date) AS first_bar FROM price_bars_shadow GROUP BY symbol) b ON b.symbol = t.symbol
        WHERE hr.event_type = 'fomc' AND hr.event_date < b.first_bar
          AND (hr.pct_change_1d IS NOT NULL OR hr.pct_change_3d IS NOT NULL OR hr.pct_change_5d IS NOT NULL)
          AND COALESCE(hr.price_source, '') <> 'stored_history'
          AND NOT EXISTS (SELECT 1 FROM security_records sr WHERE sr.symbol = t.symbol AND sr.role = 'stored_history'
                          AND hr.event_date BETWEEN sr.valid_from AND sr.valid_to)
        ORDER BY t.symbol, hr.event_date"""))).all()
    if not rows:
        return CheckResult("fomc_before_first_bar", PASS, "No FOMC move is dated before its ticker's first stored bar")
    return CheckResult("fomc_before_first_bar", ERROR, f"{len(rows)} FOMC move(s) dated before the ticker's first stored bar",
                       [f"{r.symbol}  fomc={r.event_date}  first bar={r.first_bar}  1d={r.pct_change_1d}  3d={r.pct_change_3d}  5d={r.pct_change_5d}" for r in rows[:40]])


def calendar_mismatches(bar_dates: set, start: date, end: date) -> list[str]:
    """Pure: days in [start, end] where the trading calendar and SPY's stored bars disagree."""
    from app.services.trading_calendar import is_trading_day
    out = []
    d = start
    while d <= end:
        session_by_calendar, bar = is_trading_day(d), d in bar_dates
        if session_by_calendar and not bar:
            out.append(f"{d.isoformat()}: the calendar calls it a session but SPY has no bar")
        elif bar and not session_by_calendar:
            out.append(f"{d.isoformat()}: SPY has a bar but the calendar calls it closed")
        d += timedelta(days=1)
    return out


async def check_calendar_matches_spy_bars(session) -> CheckResult:
    """ERROR when the trading calendar (services/trading_calendar) and SPY's stored bars disagree on any day from the
    first stored bar to the last: a session with no bar, or a bar on a day the calendar calls closed."""
    from app.services.security_records import STORED_START
    rows = (await session.execute(text("SELECT date FROM price_bars_shadow WHERE symbol = 'SPY' AND date >= :s ORDER BY date"), {"s": STORED_START})).scalars().all()
    if not rows:
        return CheckResult("calendar_matches_spy_bars", WARN, "No SPY bars stored: the calendar cannot be checked")
    bad = calendar_mismatches(set(rows), rows[0], rows[-1])
    if bad:
        return CheckResult("calendar_matches_spy_bars", ERROR, f"{len(bad)} day(s) where the trading calendar and SPY's bars disagree ({rows[0]}..{rows[-1]})", bad[:40])
    return CheckResult("calendar_matches_spy_bars", PASS, f"The trading calendar matches SPY's bars on every day {rows[0]}..{rows[-1]} ({len(rows)} sessions)")


# ── Duplicate reaction detection ─────────────────────────────────────────────

async def check_duplicate_earnings_reactions(session) -> CheckResult:
    """WARN listing tickers with two earnings reactions within 45 calendar days.

    Pattern: yfinance reports the same quarter under two dates (preliminary +
    confirmed, or event_date-1 acceptance). The row with known timing (bmo/amc)
    and non-null pcts is the real one; the other (usually timing=unknown, null
    pcts) is a ghost.

    Resolved by app.scripts.dedupe_earnings_reactions (identical EPS = one report).
    """
    rows = (await session.execute(text("""
        SELECT t.symbol,
               hr1.event_date AS d1, hr2.event_date AS d2,
               hr1.report_timing AS t1, hr2.report_timing AS t2,
               hr1.pct_change_1d IS NOT NULL AS has_pct1,
               hr2.pct_change_1d IS NOT NULL AS has_pct2,
               hr1.eps_estimate AS eps_est1, hr1.eps_actual AS eps_act1,
               hr2.eps_estimate AS eps_est2, hr2.eps_actual AS eps_act2
        FROM historical_reactions hr1
        JOIN historical_reactions hr2
          ON hr1.ticker_id = hr2.ticker_id
          AND hr1.event_type = 'earnings'
          AND hr2.event_type = 'earnings'
          AND hr2.event_date > hr1.event_date
          AND hr2.event_date - hr1.event_date <= 45
        JOIN tickers t ON t.id = hr1.ticker_id
        ORDER BY t.symbol, hr1.event_date
    """))).all()

    if not rows:
        return CheckResult(
            "duplicate_earnings_reactions", PASS,
            "No earnings reactions within 45 days of each other",
        )

    details = [
        f"{r.symbol}  {r.d1} ({r.t1}, {'pct' if r.has_pct1 else 'null'}, "
        f"eps={r.eps_est1}/{r.eps_act1}) ↔ "
        f"{r.d2} ({r.t2}, {'pct' if r.has_pct2 else 'null'}, "
        f"eps={r.eps_est2}/{r.eps_act2})"
        for r in rows
    ]
    return CheckResult(
        "duplicate_earnings_reactions", WARN,
        f"{len(rows)} pair(s) of earnings reactions within 45 days",
        details,
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


async def check_amc_event_day_vs_1d(session) -> CheckResult:
    """WARN listing amc tickers whose event-day move exceeds their stored 1d move.

    Mirror of bmo_1d_vs_gap. A true after-close report moves the stock the next
    session, which is what the stored 1d (close(T) -> close(T+1)) captures. If
    the event day itself (close(T-1) -> close(T)) moves more on average, the
    ticker probably reports before the open and its amc tag is wrong.
    """
    from collections import defaultdict

    rows = (await session.execute(
        select(
            Ticker.symbol,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.close_before,
            HistoricalReaction.close_after,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.report_timing == "amc",
            HistoricalReaction.pct_change_1d.isnot(None),
            HistoricalReaction.close_before.isnot(None),
            HistoricalReaction.close_after.isnot(None),
            HistoricalReaction.close_before > 0,
        )
    )).all()

    ticker_data: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        event_day = abs(float(r.close_after) - float(r.close_before)) / float(r.close_before) * 100
        ticker_data[r.symbol].append((event_day, abs(float(r.pct_change_1d))))

    flagged: list[tuple[float, str]] = []
    for sym, pairs in ticker_data.items():
        if len(pairs) < 4:
            continue
        avg_event_day = sum(p[0] for p in pairs) / len(pairs)
        avg_abs_1d = sum(p[1] for p in pairs) / len(pairs)
        if avg_event_day > avg_abs_1d:
            flagged.append((
                avg_event_day / avg_abs_1d if avg_abs_1d else float("inf"),
                f"{sym}: avg_abs_event_day={avg_event_day:.2f}%, avg_abs_1d={avg_abs_1d:.2f}%, n={len(pairs)}",
            ))

    if not flagged:
        return CheckResult(
            "amc_event_day_vs_1d", PASS,
            f"All amc tickers move more on the stored 1d than on the event day ({len(ticker_data)} tickers checked)",
        )
    flagged.sort(reverse=True)
    return CheckResult(
        "amc_event_day_vs_1d", WARN,
        f"{len(flagged)} of {len(ticker_data)} amc ticker(s) move more on the event day than on the stored 1d (possible bmo mis-tag)",
        [line for _, line in flagged],
    )


async def check_pnl_pct_units(session) -> CheckResult:
    """ERROR if a stored option P&L percentage disagrees with its own dollars.

    Every *_pnl_pct is a percent (-35.0). A row written as a fraction (-0.35)
    makes the ledger show "-0.4%" and corrupts "Avg P&L %".
    """
    # (table, label expression, FROM clause, pct column, percent implied by the row's own dollars).
    # theses carries ticker_id, not symbol, so it joins tickers like the other checks.
    targets = (
        ("alert_picks", "x.symbol", "alert_picks x",
         "x.option_pnl_pct", "x.option_pnl_dollars / NULLIF(x.cost_to_enter, 0)"),
        ("theses", "t.symbol", "theses x JOIN tickers t ON t.id = x.ticker_id",
         "x.option_pnl_pct", "x.option_pnl_dollars / NULLIF((x.entry_premium - COALESCE(x.entry_premium2, 0)) * x.contracts, 0)"),
        ("credit_shadow_picks", "x.symbol", "credit_shadow_picks x",
         "x.pnl_pct", "x.pnl_dollars / NULLIF(x.max_loss, 0)"),
    )
    bad: list[str] = []
    checked = 0
    for table, label, from_clause, col, implied in targets:
        exists = (await session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"), {"t": table})).scalar()
        if not exists:
            continue
        rows = (await session.execute(text(
            f"SELECT {label} AS label, {col} AS stored, ({implied}) AS implied FROM {from_clause} "
            f"WHERE {col} IS NOT NULL AND ({implied}) IS NOT NULL"
        ))).all()
        checked += len(rows)
        for r in rows:
            if abs(float(r.stored) - float(r.implied)) > 0.5:
                bad.append(f"{table} {r.label}: stored {float(r.stored):.4f} but dollars imply {float(r.implied):.2f}%")
    if bad:
        return CheckResult("pnl_pct_units", ERROR,
                           f"{len(bad)} P&L percentage(s) disagree with their dollars (fraction stored as percent?)", bad[:30])
    return CheckResult("pnl_pct_units", PASS, f"All {checked} stored P&L percentages match their dollars")


# ── Nightly step age ──────────────────────────────────────────────────────────

STEP_AGE_WARN_DAYS = 2
STEP_AGE_ERROR_DAYS = 4


def step_age_result(steps: dict[str, str | None], now: datetime) -> CheckResult:
    """Pure: `steps` is {label: last_success_iso | None}, the store /health reads."""
    stale_warn: list[str] = []
    stale_error: list[str] = []
    never: list[str] = []
    for label, iso in sorted(steps.items()):
        if not iso:
            never.append(label)
            continue
        try:
            last = datetime.fromisoformat(iso)
        except ValueError:
            never.append(f"{label} (unparseable: {iso})")
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_days = (now - last).total_seconds() / 86400
        line = f"{label}: last success {last.date().isoformat()} ({age_days:.1f} days ago)"
        if age_days >= STEP_AGE_ERROR_DAYS:
            stale_error.append(line)
        elif age_days >= STEP_AGE_WARN_DAYS:
            stale_warn.append(line)
    if stale_error:
        return CheckResult("step_age", ERROR,
                           f"{len(stale_error)} nightly step(s) have not succeeded in {STEP_AGE_ERROR_DAYS}+ days",
                           stale_error + stale_warn + [f"never succeeded: {n}" for n in never])
    if stale_warn or never:
        return CheckResult("step_age", WARN,
                           f"{len(stale_warn)} nightly step(s) have not succeeded in {STEP_AGE_WARN_DAYS}+ days"
                           + (f"; {len(never)} never recorded a success" if never else ""),
                           stale_warn + [f"never succeeded: {n}" for n in never])
    return CheckResult("step_age", PASS, f"All {len(steps)} nightly steps succeeded within {STEP_AGE_WARN_DAYS} days")


async def check_step_age(session) -> CheckResult:
    """WARN when a nightly step's last success is 2+ days old, ERROR at 4+ days.

    Reads step:<label>:last_success from system_metadata, the same rows /health
    reports as step_health, for every step in refresh.py's list except this one.
    """
    from app.scripts.refresh import STEPS

    rows = (await session.execute(text(
        # `\:` keeps SQLAlchemy from reading ":last_success" as a bind parameter
        r"SELECT key, value FROM system_metadata WHERE key LIKE 'step:%\:last_success'"
    ))).all()
    stored = {k[len("step:"):-len(":last_success")]: v for k, v in rows}
    steps = {label: stored.get(label) for label, _ in STEPS if label != "Validate data"}
    return step_age_result(steps, datetime.now(timezone.utc))


# ── Data age ──────────────────────────────────────────────────────────────────

DATA_AGE_MAX_SESSIONS = 3


def data_age_result(newest: dict[str, date | None], today: date) -> CheckResult:
    """Pure: `newest` is {feed: newest date | None}; WARN when any is more than 3 sessions old."""
    from app.services.trading_calendar import sessions_after

    stale: list[str] = []
    fresh: list[str] = []
    for feed, d in newest.items():
        if d is None:
            stale.append(f"{feed}: no data at all")
            continue
        missed = sessions_after(d, today)
        line = f"{feed}: newest {d.isoformat()} ({missed} sessions ago)"
        (stale if missed > DATA_AGE_MAX_SESSIONS else fresh).append(line)
    if stale:
        return CheckResult("data_age", WARN,
                           f"{len(stale)} data feed(s) older than {DATA_AGE_MAX_SESSIONS} trading days "
                           "(has the provider stopped answering?)", stale + fresh)
    return CheckResult("data_age", PASS, "; ".join(fresh))


async def check_data_age(session) -> CheckResult:
    """WARN when the newest analyst action, options chain date, or price bar is over 3 trading days old.

    These are the signals that yfinance has stopped answering the production host.
    """
    analyst = await session.scalar(text("SELECT max(event_date) FROM events WHERE event_type = 'analyst_action'"))
    chain = await session.scalar(text("SELECT max(snapshot_date) FROM put_call_snapshots"))
    bar = await session.scalar(text("""
        SELECT max(rs.last_bar_date) FROM rv_snapshots rs
        JOIN tickers t ON t.symbol = rs.symbol AND t.is_active = true
    """))
    return data_age_result(
        {"analyst actions": analyst, "options chains": chain, "price bars (rv_snapshots.last_bar_date)": bar},
        date.today(),
    )


# ── Runner ────────────────────────────────────────────────────────────────────

CHECKS = [
    # Tickers
    check_ticker_missing_metadata,
    check_ticker_market_cap,
    check_ticker_duplicate_symbols,
    check_frozen_price_history,
    check_price_history_stale,
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
    check_step_age,
    check_data_age,
    check_rv_rank_bounds,
    check_rv_data_error_tickers,
    check_rv_snapshot_coverage,
    check_news_freshness,
    check_chain_parity,
    check_excluded_ticker_hidden,
    check_analyst_stats_sessions,
    check_outcome_matches_eps,
    check_estimate_split_basis,
    check_basis_mismatch_has_no_outcome,
    check_refused_earnings_dates,
    check_cached_reads_stale,
    check_eps_basis_suspect,
    # Analyst recommendations
    check_recommendations_freshness,
    check_recommendations_bounds,
    # Alert picks
    check_pick_lifecycle,
    check_pick_void,
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
    check_pnl_pct_units,
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
    # Duplicate reactions
    check_duplicate_earnings_reactions,
    # Security records: one Intrinio record per ticker per date, FIGI unchanged
    check_security_record_coverage,
    check_figi_change,
    # Chain shadow: Intrinio's EOD chain against the courier's, judged over a week
    check_chain_shadow,
    # IV solver: against the vendor, and within its own band
    check_iv_vendor_band,
    check_iv_solver_band,
    # Reaction rows name their bars; sources mix only across a stored_history span
    check_reaction_source_coverage,
    check_reaction_source_consistency,
    # Stored splits agree with the shadow bars' factors
    check_split_factor_match,
    # Someone is told when something fails
    check_alerting_configured,
    # Identity: symbols follow Intrinio, half-delisted tickers do not stay active, pending repairs are named
    check_symbol_matches_record,
    check_delisting_signals,
    check_pending_repairs,
    # EPS actuals the night of the report
    check_eps_actuals_fresh,
    # one earnings event per ticker and date
    check_earnings_events_unique,
    # an as-of is when we knew: no source dated after today
    check_as_of_not_future,
    # dividends: the next amount is a payment, in line with the last
    check_next_dividend_amount,
    check_pe_window_fresh,
    check_release_eps_checked,
    check_share_count_jumps,
    check_eps_quarter_outliers,
    check_pe_sanity,
    # the calendar: confirmed dates stand alone, past estimates never stand as resolved
    check_estimate_beside_confirmed,
    check_past_estimate_standing,
    # prices behind every reaction; RV really recomputed
    check_reactions_after_first_bar,
    check_rv_snapshot_unchanged,
    # FOMC decision days: official set, one event per meeting, the Fed page agrees
    check_fomc_dates_official,
    check_fomc_events_unique,
    check_fomc_calendar_matches_fed,
    # Pre-listing FOMC guard
    check_fomc_before_first_bar,
    # The trading calendar agrees with the stored sessions
    check_calendar_matches_spy_bars,
    # v3 reaction checks
    check_no_mixed_computation_version,
    check_report_timing_unknown_share,
    check_bmo_1d_vs_gap,
    check_amc_event_day_vs_1d,
]


def _icon(level: str) -> str:
    return {"pass": "✓", "warn": "⚠", "error": "✗"}.get(level, "?")


async def run_checks(checks, session_factory=None) -> list[CheckResult]:
    """Run every check in its own session.

    A check that raises is recorded as an ERROR and the rest still run. On
    Postgres a failed statement aborts the whole transaction, so sharing one
    session would turn a single bad query into "current transaction is
    aborted" for every check after it.
    """
    session_factory = session_factory or AsyncSessionLocal
    results: list[CheckResult] = []
    for check_fn in checks:
        try:
            async with session_factory() as session:
                result = await check_fn(session)
        except Exception as exc:
            result = CheckResult(check_fn.__name__, ERROR, f"Check raised an exception: {redact(exc)}")
        results.append(result)
    return results


VALIDATE_STEP_LABEL = "Validate data"     # the label in refresh.STEPS


async def write_holds(results: list[CheckResult], session_factory=None) -> list[dict]:
    """Fail closed: the per-ticker facts the ERROR checks judged wrong, replaced into fact_holds (services/fact_holds)."""
    from app.services.fact_holds import holds_from_results, replace_holds
    factory = session_factory or AsyncSessionLocal
    async with factory() as session:
        symbols = set((await session.execute(text("SELECT symbol FROM tickers"))).scalars().all())
        holds = holds_from_results(results, symbols)
        await replace_holds(session, holds)
        await session.commit()
    return holds
OUTCOME_ERROR_CAP = 10


def outcome_fields(results: list[CheckResult], holds: list[dict] | None = None) -> dict:
    """What /health carries for this run: counts, the failing checks with their one-line messages, and the facts held (hidden) per ticker."""
    from app.services.fact_holds import hidden_lines
    errors = [r for r in results if r.level == ERROR]
    figures: dict = {}
    for r in results:
        figures.update(r.figures or {})
    hidden = hidden_lines(holds or [])
    return {
        "pass_count": sum(1 for r in results if r.level == PASS),
        "warn_count": sum(1 for r in results if r.level == WARN),
        "error_count": len(errors),
        "errors": [{"check": r.name, "message": r.message} for r in errors[:OUTCOME_ERROR_CAP]],
        "figures": figures,
        "hidden_count": len(hidden),
        "hidden": hidden[:80],
    }


VALIDATE_ALERT_CAP = 10          # one ntfy message per ERROR up to this many, then one that counts the rest


async def alert_errors(results: list) -> int:
    """One ntfy message per ERROR (services/notify); returns how many were sent."""
    from app.services.notify import PRIORITY_HIGH, notify, validate_error_message
    errors = [r for r in results if r.level == ERROR]
    sent = 0
    for r in errors[:VALIDATE_ALERT_CAP]:
        title, body = validate_error_message(r.name, r.message, r.rows)
        sent += await notify(title, body, PRIORITY_HIGH, ("rotating_light",))
    if len(errors) > VALIDATE_ALERT_CAP:
        sent += await notify("Validate ERROR: more", f"{len(errors) - VALIDATE_ALERT_CAP} further check(s) in error; see /health", PRIORITY_HIGH, ("rotating_light",))
    return sent


async def main() -> int:
    from app.services.step_outcomes import record_step_fields

    results = await run_checks(CHECKS)
    holds = await write_holds(results)
    await record_step_fields(VALIDATE_STEP_LABEL, outcome_fields(results, holds))
    await alert_errors(results)
    if holds:
        print(f"\n  fail closed: {len(holds)} fact(s) hidden until their check passes")

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
