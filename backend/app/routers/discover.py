from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from app.services.recommendations import buy_share_delta, buy_share_line
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Date as SADate, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.discover_blurbs import MIN_QUARTERS, earnings_blurb, reaction_blurb, volatility_blurb
from app.services.pnl_math import pnl_percent
from app.auth import may_read_ledger
from app.services.earnings_calendar import level_of
from app.services.next_earnings import batch_next_earnings
from app.constants import LEDGER_PUBLIC, LEDGER_START
from app.thresholds import (
    DISCOVER_IV_RICH_PP, DISCOVER_IV_CHEAP_PP,
    DISCOVER_EXTREME_RV, DISCOVER_ELEVATED_RV,
    discover_rv_tier,
)
from app.database import get_db
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.enums import EventType
from app.models.event import Event
from app.models.eps_basis_check import EpsBasisCheck
from app.services.basis_exclusion import excluded_note
from app.services.price_history_exclusion import EXCLUDED_SYMBOLS_SQL, EXCLUSION_REASON, excluded_symbols, not_excluded
from app.services.pending_deals import not_held
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker

router = APIRouter(prefix="/discover", tags=["discover"])

# Minimum quarters for conditional earnings insight lines
_MIN_QUARTERS = MIN_QUARTERS


# ── Response models ──────────────────────────────────────────────────────────


class ReportingSoonItem(BaseModel):
    symbol: str
    name: str | None
    sector: str | None = None
    industry: str | None = None
    earnings_date: str  # ISO date
    is_confirmed: bool
    source: str | None = None        # events.source of the date ("finnhub", "yfinance", ...)
    checked_at: str | None = None    # tickers.earnings_checked_at: when Finnhub was last asked about this ticker
    confirmation: str | None = None  # "confirmed" | "estimated" | "expected_unconfirmed"
    confirmation_note: str | None = None
    insight: str | None = None  # e.g. "Beat 18 of 20 — beats largely priced in"
    vol_regime: str | None = None  # "iv_rich" | "iv_cheap" | None
    iv_rv_note: str | None = None  # "one session dominates the 20-day window: Oct 5, 2026 (+33.5%)" in place of the comparison
    implied_move_pct: float | None = None   # the freshest chain's ATM straddle over spot, percent
    chain_date: str | None = None           # that chain's date: the implied move's receipt
    typical_move_pct: float | None = None   # mean absolute 1-day move over at least 8 stored reports
    typical_n: int | None = None
    move_comparison: str | None = None      # "more than usual" | "less than usual" | "about its usual"
    comparison: str | None = None           # the one sentence, services/move_comparison


class ReportingSoonResponse(BaseModel):
    items: list[ReportingSoonItem]
    total: int


class SuggestionItem(BaseModel):
    symbol: str
    name: str | None
    sector: str | None = None
    industry: str | None = None
    score: float
    reports_in_days: int | None
    recent_move_pct: float | None
    recent_move_5d: float | None
    recent_outcome: str | None  # beat / miss / meet / unknown
    event_date: str | None  # ISO date of the reaction's report
    insight: str | None = None
    vol_regime: str | None = None
    iv_rv_note: str | None = None
    earnings_date: str | None = None        # next stored earnings date, None when the calendar has none
    earnings_source: str | None = None      # events.source of that date
    earnings_checked_at: str | None = None  # when Finnhub was last asked (tickers.earnings_checked_at)
    earnings_confirmation: str | None = None   # "confirmed" | "estimated" | "expected_unconfirmed"
    earnings_note: str | None = None


async def _batch_next_earnings(db: AsyncSession, symbols: list[str]) -> dict[str, dict]:
    """{symbol: {earnings_date, earnings_source, earnings_checked_at, earnings_confirmation, earnings_note}} for the
    cards, from the one chooser every page uses (services.next_earnings)."""
    if not symbols:
        return {}
    rows = (await db.execute(select(Ticker.id, Ticker.symbol).where(Ticker.symbol.in_(symbols)))).all()
    by_id = {r.id: r.symbol for r in rows}
    picked = await batch_next_earnings(db, list(by_id))
    out: dict[str, dict] = {}
    for tid, sym in by_id.items():
        ne = picked.get(tid)
        if ne is None:
            continue
        out[sym] = {
            "earnings_date": ne.date.isoformat() if ne.date else None,
            "earnings_source": ne.source,
            "earnings_checked_at": ne.checked_at.isoformat() if ne.checked_at else None,
            "earnings_confirmation": ne.confirmation,
            "earnings_note": ne.note,
        }
    return out


class SuggestionsResponse(BaseModel):
    items: list[SuggestionItem]


class JustReportedItem(BaseModel):
    symbol: str
    name: str | None
    sector: str | None = None
    industry: str | None = None
    event_date: str  # ISO date
    pct_change_1d: float | None
    outcome: str  # beat / miss / meet / unknown
    insight: str | None = None  # e.g. "Moved -6.3% vs +2.7% typical beat"
    vol_regime: str | None = None
    iv_rv_note: str | None = None


class JustReportedResponse(BaseModel):
    items: list[JustReportedItem]
    total: int


class UnusuallyActiveItem(BaseModel):
    symbol: str
    name: str | None
    sector: str | None = None
    industry: str | None = None
    rv_rank: float
    rv_20d: float
    tier: str  # "extreme" or "elevated"
    insight: str | None = None  # e.g. "IV rich +12pp — options expensive vs realized"
    vol_regime: str | None = None
    iv_rv_note: str | None = None
    # the Tape's words are built from these (frontend discoverSentences.unusuallyActiveSentence); the figures go to the row's hover
    iv_rv_spread_pp: float | None = None       # implied minus realized, in points; None without a fresh chain or when one session dominates
    atm_iv: float | None = None
    iv_date: str | None = None                 # the chain's date
    dominant_date: str | None = None           # the session that dominates the 20-day window, when one does
    dominant_move_pct: float | None = None
    rank_hold_phrase: str | None = None        # "Spun off Vylor on Oct 1": the action that holds the rank
    rank_hold_reason: str | None = None
    earnings_date: str | None = None
    earnings_source: str | None = None
    earnings_checked_at: str | None = None
    earnings_confirmation: str | None = None   # "confirmed" | "estimated" | "expected_unconfirmed"
    earnings_note: str | None = None


class UnusuallyActiveResponse(BaseModel):
    items: list[UnusuallyActiveItem]


class InsightResponse(BaseModel):
    insight: str | None = None
    rule: str | None = None
    as_of: str | None = None      # the date of the stored stat the line rests on: the newest earnings reaction, or the latest recommendation period


INSIGHT_GENERATOR_RULES: dict[str, str] = {
    "beat_rate": "Compared this stock's beat rate to the S&P 500 median beat rate",
    "priced_in": "Compared this stock's beat-but-dropped rate to the S&P 500 median",
    "avg_move": "Compared this stock's average earnings-day move to the S&P 500 median move",
    "miss_skew": "Compared the average drop on misses to the average gain on beats",
    "buy_delta": "Measured the change in analyst buy-share over the past 3 months versus the universe",
}


class LatestPickItem(BaseModel):
    id: str
    symbol: str
    picked_direction: str
    strategy: str | None
    entry_price: float
    current_price: float | None
    price_as_of: str | None = None       # ISO last-trade time of the quote shown; never the request time
    quote_reason: str | None = None      # why no current price is shown (price_freshness)
    unrealized_move_pct: float | None
    status: str
    generated_at: str
    expiration: str | None
    direction_hit: bool | None = None
    option_pnl_pct: float | None = None


class LatestPickResponse(BaseModel):
    pick: LatestPickItem | None


# ── Batch helpers (no N+1) ──────────────────────────────────────────────────


async def _batch_conditional_stats(
    db: AsyncSession, symbols: list[str],
) -> dict[str, dict]:
    """Batch-fetch conditional earnings stats for a set of symbols.

    Returns {symbol: {beat_count, total, avg_1d_on_beat, avg_1d_on_miss, ...}}.
    Single query, no N+1.
    """
    if not symbols:
        return {}

    stmt = (
        select(
            Ticker.symbol,
            HistoricalReaction.outcome,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.event_date,
            EpsBasisCheck.basis_mismatch,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .outerjoin(EpsBasisCheck, (EpsBasisCheck.ticker_id == HistoricalReaction.ticker_id)
                   & (EpsBasisCheck.event_date == HistoricalReaction.event_date))
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.symbol.in_(symbols),
            not_excluded(Ticker.symbol),
        )
        .order_by(HistoricalReaction.event_date.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Aggregate per symbol; quarters whose EPS basis is unclear leave every count
    by_sym: dict[str, list[tuple]] = {}
    excluded: dict[str, int] = {}
    newest: dict[str, date] = {}            # the newest quarter in each symbol's sample: the stat's as-of date
    for r in rows:
        if r.basis_mismatch:
            excluded[r.symbol] = excluded.get(r.symbol, 0) + 1
            continue
        by_sym.setdefault(r.symbol, []).append((r.outcome, float(r.pct_change_1d)))
        if r.symbol not in newest or r.event_date > newest[r.symbol]:
            newest[r.symbol] = r.event_date

    out: dict[str, dict] = {}
    for sym, quarters in by_sym.items():
        total = len(quarters)
        beat_moves = [m for o, m in quarters if o and o.value == "beat"]
        miss_moves = [m for o, m in quarters if o and o.value == "miss"]
        beat_count = len(beat_moves)
        miss_count = len(miss_moves)

        avg_1d_on_beat = round(sum(beat_moves) / beat_count, 2) if beat_count else None
        avg_1d_on_miss = round(sum(miss_moves) / miss_count, 2) if miss_count else None

        # "Beat-but-dropped" count
        bbd = sum(1 for m in beat_moves if m < 0)

        all_abs = [abs(m) for _, m in quarters]
        avg_abs_1d = round(sum(all_abs) / len(all_abs), 2) if all_abs else None

        out[sym] = {
            "as_of": newest[sym].isoformat(),
            "total": total,
            "beat_count": beat_count,
            "miss_count": miss_count,
            "bbd_count": bbd,
            "avg_1d_on_beat": avg_1d_on_beat,
            "avg_1d_on_miss": avg_1d_on_miss,
            "avg_abs_1d": avg_abs_1d,
            "basis_excluded": excluded.get(sym, 0),
        }
    return out


async def _batch_vol_regime(
    db: AsyncSession, symbols: list[str],
) -> dict[str, dict]:
    """Batch-fetch IV-RV spread for symbols from latest iv_history + rv_snapshots.

    Returns {symbol: {iv_rv_spread_pp, vol_regime, atm_iv, rv_20d}}.
    Two queries total.
    """
    if not symbols:
        return {}

    # Latest IV per symbol — use iv_history with DISTINCT ON
    # each ticker's IV from its serving chain source (services/options_source); a ticker whose options are hidden has none
    from app.services.options_source import IV_SOURCE, resolve
    from app.config import settings
    serving_src = {}
    for sym in symbols:
        sv = await resolve(db, sym)
        if sv.source:
            serving_src[sym] = IV_SOURCE[sv.source]
        elif not sv.hidden_by_check:
            serving_src[sym] = IV_SOURCE[settings.options_primary_source]     # no chain at all: the primary's rows, as before
    iv_stmt = sa.text("""
        SELECT DISTINCT ON (symbol, iv_source) symbol, atm_iv, date, iv_source
        FROM iv_history
        WHERE symbol = ANY(:syms) AND iv_source IN ('courier', 'intrinio_mid')
        ORDER BY symbol, iv_source, date DESC
    """)
    iv_result = await db.execute(iv_stmt, {"syms": list(serving_src)})
    iv_map: dict[str, float] = {}
    iv_dates: dict[str, date] = {}
    for r in iv_result.all():
        if r.atm_iv is not None and r.iv_source == serving_src.get(r.symbol):      # only the serving source's row
            iv_map[r.symbol] = float(r.atm_iv)
            iv_dates[r.symbol] = r.date

    # Latest RV per symbol
    from app.services.rv_hold import hold_phrase, hold_reason, rank_hold_actions
    from app.services.rv_store import dominant_note, get_latest_rv_bulk
    rv_rows = await get_latest_rv_bulk(db, symbols)

    today = date.today()
    actions = await rank_hold_actions(db, symbols, today)     # the rank is held after a corporate action inside the last 252 sessions
    holds = {sym: hold_reason(a["kind"], a["name"], a["date"]) for sym, a in actions.items()}
    out: dict[str, dict] = {}
    for sym in symbols:
        atm_iv = iv_map.get(sym)
        rv_row = rv_rows.get(sym)
        rv_20d = float(rv_row.rv_20d) if rv_row and rv_row.rv_20d else None
        rv_rank = float(rv_row.rv_rank) if rv_row and rv_row.rv_rank and sym not in holds else None
        note = dominant_note(rv_row) if rv_row else None

        # Only compute spread if IV data is fresh (<= 5 calendar days)
        iv_date = iv_dates.get(sym)
        if atm_iv is not None and iv_date and (today - iv_date).days > 5:
            atm_iv = None  # stale IV, skip

        if note is not None:
            spread_pp = None             # one session dominates the window: the comparison and its rich/cheap label are not shown
            regime = None
        elif atm_iv is not None and rv_20d is not None and rv_20d > 0:
            spread_pp = round((atm_iv - rv_20d) * 100, 1)
            if spread_pp > DISCOVER_IV_RICH_PP:
                regime = "iv_rich"
            elif spread_pp < DISCOVER_IV_CHEAP_PP:
                regime = "iv_cheap"
            else:
                regime = None  # no chip
        else:
            spread_pp = None
            regime = None

        out[sym] = {
            "iv_rv_spread_pp": spread_pp,
            "vol_regime": regime,
            "atm_iv": atm_iv,
            "rv_20d": rv_20d,
            "rv_rank": rv_rank,
            "iv_rv_note": note,
            "rv_rank_hold": holds.get(sym),
            "rank_hold_phrase": hold_phrase(actions[sym]["kind"], actions[sym]["name"], actions[sym]["date"]) if sym in actions else None,
            "iv_date": iv_dates.get(sym).isoformat() if atm_iv is not None and iv_dates.get(sym) else None,
            "dominant_date": rv_row.dominant_date.isoformat() if note is not None and getattr(rv_row, "dominant_date", None) else None,
            "dominant_move_pct": float(rv_row.dominant_move_pct) if note is not None and getattr(rv_row, "dominant_move_pct", None) is not None else None,
        }
    return out


async def _batch_analyst_stats(
    db: AsyncSession, symbols: list[str],
) -> dict[str, dict]:
    """Batch-fetch analyst reaction stats for symbols.

    Returns {symbol: {upgrade_count, downgrade_count, avg_1d_downgrade, ...}}.
    """
    if not symbols:
        return {}

    stmt = sa.text("""
        SELECT symbol, upgrade_count, downgrade_count,
               avg_1d_upgrade, avg_1d_downgrade,
               downgrade_5d_continuation_pct, upgrade_5d_continuation_pct
        FROM analyst_reaction_stats
        WHERE symbol = ANY(:syms) AND symbol NOT IN """ + EXCLUDED_SYMBOLS_SQL + """
    """)
    result = await db.execute(stmt, {"syms": symbols})

    out: dict[str, dict] = {}
    for r in result.all():
        out[r.symbol] = {
            "upgrade_count": r.upgrade_count or 0,
            "downgrade_count": r.downgrade_count or 0,
            "avg_1d_upgrade": float(r.avg_1d_upgrade) if r.avg_1d_upgrade else None,
            "avg_1d_downgrade": float(r.avg_1d_downgrade) if r.avg_1d_downgrade else None,
            "downgrade_5d_cont": float(r.downgrade_5d_continuation_pct) if r.downgrade_5d_continuation_pct else None,
            "upgrade_5d_cont": float(r.upgrade_5d_continuation_pct) if r.upgrade_5d_continuation_pct else None,
        }
    return out


# ── Buy-share delta helper ───────────────────────────────────────────────────


async def _batch_buy_share_delta(
    db: AsyncSession, symbols: list[str],
) -> dict[str, dict]:
    """Compute buy-share delta (latest vs ~3 months ago) from analyst_recommendations.

    Returns {symbol: {buy_share, delta, total}}.
    """
    if not symbols:
        return {}

    # Get ticker_ids for the symbols
    ticker_q = await db.execute(
        select(Ticker.id, Ticker.symbol).where(Ticker.symbol.in_(symbols))
    )
    ticker_map = {row.id: row.symbol for row in ticker_q.all()}
    if not ticker_map:
        return {}

    # Fetch all recommendation rows for these tickers
    recs = (await db.execute(
        select(AnalystRecommendation)
        .where(AnalystRecommendation.ticker_id.in_(list(ticker_map.keys())))
        .order_by(AnalystRecommendation.period.desc())
    )).scalars().all()

    # Group by ticker
    by_ticker: dict[str, list] = {}
    for r in recs:
        sym = ticker_map.get(r.ticker_id)
        if sym:
            by_ticker.setdefault(sym, []).append(r)

    now = datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for sym, rows in by_ticker.items():
        buy = buy_share_delta(rows, now)        # None when the trend is stale (services/recommendations.MAX_AGE_DAYS) or too thin
        if buy is not None:
            out[sym] = buy

    return out


# ── Universe base rates ──────────────────────────────────────────────────────

_base_rates_cache: dict | None = None
_base_rates_date: date | None = None


async def _get_base_rates(db: AsyncSession) -> dict:
    """Compute universe-wide base rates for z-score insight selection.

    Cached per calendar day (one DB pass per day of server uptime).
    Returns medians and standard deviations for each generator's key metric.
    """
    global _base_rates_cache, _base_rates_date
    today = date.today()
    if _base_rates_cache is not None and _base_rates_date == today:
        return _base_rates_cache

    # 1) Beat rates and avg_abs_1d per ticker
    stmt = (
        select(
            Ticker.symbol,
            HistoricalReaction.outcome,
            HistoricalReaction.pct_change_1d,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.is_active.is_(True),
            Ticker.index_member.is_(True),          # "the S&P 500 median" means index members; seed_sp500 keeps the flag nightly
            not_excluded(Ticker.symbol),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    by_sym: dict[str, list[tuple]] = {}
    for r in rows:
        by_sym.setdefault(r.symbol, []).append((r.outcome, float(r.pct_change_1d)))

    beat_rates: list[float] = []
    bbd_rates: list[float] = []
    avg_abs_moves: list[float] = []
    miss_ratios: list[float] = []  # |avg_miss| / |avg_beat|

    for sym, quarters in by_sym.items():
        total = len(quarters)
        if total < _MIN_QUARTERS:
            continue
        beat_moves = [m for o, m in quarters if o and o.value == "beat"]
        miss_moves = [m for o, m in quarters if o and o.value == "miss"]
        bc = len(beat_moves)

        if bc > 0:
            beat_rates.append(bc / total)
        if bc >= 4:
            bbd = sum(1 for m in beat_moves if m < 0)
            bbd_rates.append(bbd / bc)

        all_abs = [abs(m) for _, m in quarters]
        avg_abs_moves.append(sum(all_abs) / len(all_abs))

        avg_beat = sum(beat_moves) / bc if bc else None
        mc = len(miss_moves)
        avg_miss = sum(miss_moves) / mc if mc else None
        if avg_beat is not None and avg_miss is not None and abs(avg_beat) > 0:
            miss_ratios.append(abs(avg_miss) / abs(avg_beat))

    # 2) Buy-share deltas from analyst_recommendations
    rec_stmt = (
        select(AnalystRecommendation)
        .join(Ticker, Ticker.id == AnalystRecommendation.ticker_id)
        .where(Ticker.is_active.is_(True))
        .order_by(AnalystRecommendation.ticker_id, AnalystRecommendation.period.desc())
    )
    rec_rows = (await db.execute(rec_stmt)).scalars().all()

    rec_by_ticker: dict[str, list] = {}
    for r in rec_rows:
        rec_by_ticker.setdefault(str(r.ticker_id), []).append(r)

    buy_deltas: list[float] = []
    for rows_list in rec_by_ticker.values():
        if not rows_list:
            continue
        latest = rows_list[0]
        earlier = None
        for r in rows_list:
            if (latest.period - r.period).days >= 60:
                earlier = r
                break
        if earlier is None:
            continue
        def _bs(r):
            tot = r.strong_buy + r.buy + r.hold + r.sell + r.strong_sell
            return ((r.strong_buy + r.buy) / tot, tot) if tot else (0, 0)
        ls, lt = _bs(latest)
        es, et = _bs(earlier)
        if lt >= 5 and et >= 5:
            buy_deltas.append(ls - es)

    def _stats(vals: list[float]) -> tuple[float | None, float]:
        if len(vals) < 3:
            return (None, 1.0)    # no median: an insight says the comparison is unavailable, never "0%"
        vals_s = sorted(vals)
        med = vals_s[len(vals_s) // 2]
        variance = sum((v - med) ** 2 for v in vals_s) / len(vals_s)
        sd = math.sqrt(variance) if variance > 0 else 1.0
        return (med, sd)

    br_med, br_sd = _stats(beat_rates)
    bbd_med, bbd_sd = _stats(bbd_rates)
    am_med, am_sd = _stats(avg_abs_moves)
    mr_med, mr_sd = _stats(miss_ratios)
    bd_med, bd_sd = _stats(buy_deltas)

    _base_rates_cache = {
        "beat_rate": {"med": br_med, "sd": br_sd},
        "bbd_rate": {"med": bbd_med, "sd": bbd_sd},
        "avg_abs_move": {"med": am_med, "sd": am_sd},
        "miss_ratio": {"med": mr_med, "sd": mr_sd},
        "buy_delta": {"med": bd_med, "sd": bd_sd},
    }
    _base_rates_date = today
    return _base_rates_cache


# ── Insight-line builders ────────────────────────────────────────────────────


def _reporting_soon_insight(cond: dict | None, symbol: str = "") -> str | None:
    return earnings_blurb(cond)


def _just_reported_insight(
    pct_1d: float | None, outcome: str, cond: dict | None, symbol: str = "",
) -> str | None:
    return reaction_blurb(pct_1d, outcome, cond)


# An insight compares a stock to the S&P median. When that median is not there the
# line says so and why; it never prints the placeholder ("versus ±0.0% across the S&P").
INDEX_BASE_NOT_LOADED = "S&P comparison unavailable: index medians were not loaded for this view"
INDEX_BASE_TOO_FEW = "S&P comparison unavailable: fewer than 3 tickers have this stat stored"
INDEX_BASE_ZERO = "S&P comparison unavailable: the stored index median is zero, which is not a real value"


def _index_median(base: dict, key: str) -> tuple[float | None, str | None]:
    """(median, None) when the index median for ``key`` is usable, else (None, reason)."""
    stat = base.get(key)
    if not stat:
        return None, INDEX_BASE_NOT_LOADED
    med = stat.get("med")
    if med is None:
        return None, INDEX_BASE_TOO_FEW
    if med == 0:
        return None, INDEX_BASE_ZERO
    return med, None


def _z(value: float, base: dict, key: str) -> float:
    """|z| of ``value`` against the index; 0 when there is no index median to compare with."""
    med, _ = _index_median(base, key)
    if med is None:
        return 0.0
    return abs(value - med) / (base[key].get("sd") or 1.0)


def _versus_index(base: dict, key: str, fmt) -> str:
    med, reason = _index_median(base, key)
    return f"versus {fmt(med)} across the S&P" if med is not None else f"({reason})"


def _suggestion_insight(
    cond: dict | None, analyst: dict | None,
    buy_share: dict | None, base: dict | None,
    symbol: str = "",
) -> tuple[str | None, str | None, float]:
    """Pick the most distinctive insight by |z-score| vs universe base rates.

    Returns (insight_line, generator_name, abs_z).
    """
    candidates: list[tuple[str, float, str]] = []  # (line, |z|, generator_name)

    if base is None:
        base = {}

    def _excluded_suffix(c: dict) -> str:
        note = excluded_note(c.get("basis_excluded", 0))
        return f" ({note})" if note else ""

    # ── Generator: beat_rate ─────────────────────────────────────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond["beat_count"] > 0:
        beat_rate = cond["beat_count"] / cond["total"]
        z = _z(beat_rate, base, "beat_rate")
        pct = round(beat_rate * 100)
        versus = _versus_index(base, "beat_rate", lambda m: f"{round(m * 100)}%")
        candidates.append((
            f"Beats estimates {pct}% of the time, {versus}" + _excluded_suffix(cond),
            z, "beat_rate",
        ))

    # ── Generator: priced_in (beat-but-dropped rate) ─────────────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond["beat_count"] >= 4 and cond["bbd_count"] >= 2:
        bbd_rate = cond["bbd_count"] / cond["beat_count"]
        z = _z(bbd_rate, base, "bbd_rate")
        pct = round(bbd_rate * 100)
        versus = _versus_index(base, "bbd_rate", lambda m: f"{round(m * 100)}%")
        candidates.append((
            f"Sells off after {pct}% of beats, {versus}" + _excluded_suffix(cond),
            z, "priced_in",
        ))

    # ── Generator: avg_move (average absolute earnings move) ─────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond.get("avg_abs_1d") is not None:
        avg = cond["avg_abs_1d"]
        z = _z(avg, base, "avg_abs_move")
        med, _ = _index_median(base, "avg_abs_move")
        if med is not None and avg >= med * 1.8:
            ratio = f"{avg / med:.1f}x the index median"
        else:
            ratio = _versus_index(base, "avg_abs_move", lambda m: f"{chr(0xB1)}{m:.1f}%")
        candidates.append((
            f"Averages a {chr(0xB1)}{avg:.1f}% earnings move, {ratio}",
            z, "avg_move",
        ))

    # ── Generator: miss_skew (miss penalty vs beat reward asymmetry) ─────────
    if cond and cond["total"] >= _MIN_QUARTERS:
        avg_beat = cond.get("avg_1d_on_beat")
        avg_miss = cond.get("avg_1d_on_miss")
        if avg_beat is not None and avg_miss is not None and abs(avg_beat) > 0 and cond["miss_count"] >= 2:
            ratio = abs(avg_miss) / abs(avg_beat)
            z = _z(ratio, base, "miss_ratio")
            candidates.append((
                f"Misses cost {abs(avg_miss):.1f}% avg vs +{abs(avg_beat):.1f}% on beats",
                z, "miss_skew",
            ))

    # ── Generator: buy_delta (analyst buy-share shift) ───────────────────────
    if buy_share:
        z = _z(buy_share["delta"], base, "buy_delta")
        candidates.append((buy_share_line(buy_share), z, "buy_delta"))

    if not candidates:
        return None, None, 0.0

    candidates.sort(key=lambda x: -x[1])
    line, z, gen = candidates[0]
    return line, gen, z


def _unusually_active_insight(vol: dict | None, symbol: str = "") -> str | None:
    if not vol:
        return None
    return volatility_blurb(vol.get("iv_rv_spread_pp"), vol.get("vol_regime"), vol.get("rv_rank"), vol.get("iv_rv_note"))


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/reporting-soon", response_model=ReportingSoonResponse)
async def reporting_soon(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> ReportingSoonResponse:
    """Universe tickers with earnings in the next N days, soonest first.
    Within same day: ranked by avg absolute earnings move desc."""
    today = date.today()
    cutoff = today + timedelta(days=days)

    q = (
        select(Ticker.symbol, Ticker.name, Ticker.sector, Ticker.industry, Event.event_date, Event.is_confirmed,
               Event.source, Ticker.earnings_checked_at, Event.unresolved_since, Event.confirmation_note)
        .join(Event, Event.ticker_id == Ticker.id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date >= today,
            Event.event_date <= cutoff,
            Ticker.is_active.is_(True),
        )
        .order_by(Event.event_date, Ticker.symbol)
    )

    result = await db.execute(q)

    # Deduplicate by symbol (keep earliest date)
    seen: set[str] = set()
    deduped = []
    for r in result.all():
        if r.symbol not in seen:
            seen.add(r.symbol)
            deduped.append(r)

    symbols = [r.symbol for r in deduped]

    # Batch intelligence
    cond_stats = await _batch_conditional_stats(db, symbols)
    vol_data = await _batch_vol_regime(db, symbols)
    # fail closed (services/fact_holds): a ticker whose report date is held leaves the list; a held typical move or implied move drops its insight and comparison
    from app.services.fact_holds import holds_for_symbols
    held = await holds_for_symbols(db, symbols)
    deduped = [r for r in deduped if "report_date" not in held.get(r.symbol, set())]
    for sym, facts in held.items():
        if "typical_move" in facts:
            cond_stats.pop(sym, None)
    comparisons = await _batch_move_comparison(db, deduped, cond_stats, today)
    for sym, facts in held.items():
        if "implied_move" in facts:
            comparisons.pop(sym, None)

    # Build items with insights
    raw_items = []
    for r in deduped:
        cond = cond_stats.get(r.symbol)
        vol = vol_data.get(r.symbol)
        # Sort key: same-day tiebreak by avg absolute move (desc)
        avg_abs = cond["avg_abs_1d"] if cond and cond.get("avg_abs_1d") else 0.0
        raw_items.append((r, cond, vol, avg_abs))

    # Sort: primary by event_date ASC, secondary by avg_abs_1d DESC
    raw_items.sort(key=lambda x: (x[0].event_date, -x[3]))

    items = [
        ReportingSoonItem(
            symbol=r.symbol,
            name=r.name,
            sector=r.sector,
            industry=r.industry,
            earnings_date=r.event_date.isoformat(),
            source=getattr(r.source, "value", r.source) if r.source is not None else None,
            checked_at=r.earnings_checked_at.isoformat() if r.earnings_checked_at else None,
            confirmation=level_of(r.is_confirmed, r.unresolved_since),
            confirmation_note=r.confirmation_note,
            is_confirmed=r.is_confirmed,
            insight=_reporting_soon_insight(cond, r.symbol),
            vol_regime=vol["vol_regime"] if vol else None,
            iv_rv_note=vol.get("iv_rv_note") if vol else None,
            **comparisons.get(r.symbol, {}),
        )
        for r, cond, vol, _ in raw_items[:limit]
    ]

    return ReportingSoonResponse(items=items, total=len(deduped))


@router.get("/just-reported", response_model=JustReportedResponse)
async def just_reported(
    days: int = Query(5, ge=1, le=30),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> JustReportedResponse:
    """Recent earnings reactions. Within same date: sorted by |move| desc."""
    cutoff = date.today() - timedelta(days=days)

    q = (
        select(
            Ticker.symbol,
            Ticker.name,
            Ticker.sector,
            Ticker.industry,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.outcome,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.event_date >= cutoff,
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.is_active.is_(True),
            not_excluded(Ticker.symbol),
            not_held(Ticker.symbol),              # a pending cash deal pauses earnings figures (services/pending_deals)
        )
        .order_by(HistoricalReaction.event_date.desc(), Ticker.symbol)
    )

    result = await db.execute(q)

    # Deduplicate by symbol (keep most-recent)
    seen: set[str] = set()
    deduped = []
    for r in result.all():
        if r.symbol not in seen:
            seen.add(r.symbol)
            deduped.append(r)

    symbols = [r.symbol for r in deduped]

    # Batch intelligence
    cond_stats = await _batch_conditional_stats(db, symbols)
    vol_data = await _batch_vol_regime(db, symbols)

    # Build + re-sort: most recent first, then by |move| desc within same date
    raw_items = []
    for r in deduped:
        cond = cond_stats.get(r.symbol)
        vol = vol_data.get(r.symbol)
        pct = float(r.pct_change_1d) if r.pct_change_1d is not None else 0.0
        outcome = r.outcome.value if r.outcome else "unknown"
        raw_items.append((r, cond, vol, pct, outcome))

    # Sort: primary by event_date DESC, secondary by |pct_change_1d| DESC
    raw_items.sort(key=lambda x: (-x[0].event_date.toordinal(), -abs(x[3])))

    items = [
        JustReportedItem(
            symbol=r.symbol,
            name=r.name,
            sector=r.sector,
            industry=r.industry,
            event_date=r.event_date.isoformat(),
            pct_change_1d=round(pct, 2) if pct else None,
            outcome=outcome,
            insight=_just_reported_insight(pct, outcome, cond, r.symbol),
            vol_regime=vol["vol_regime"] if vol else None,
            iv_rv_note=vol.get("iv_rv_note") if vol else None,
        )
        for r, cond, vol, pct, outcome in raw_items[:limit]
    ]

    return JustReportedResponse(items=items, total=len(deduped))


@router.get("/suggestions", response_model=SuggestionsResponse)
async def suggestions(
    limit: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
) -> SuggestionsResponse:
    """Top tickers by convergence of cheap signals (no LLM, no external calls)."""
    today = date.today()

    # ── Signal 1: earnings proximity (next 14 days) ──────────────────────────
    earnings_q = (
        select(Ticker.symbol, Ticker.name, Ticker.sector, Ticker.industry, Event.event_date)
        .join(Event, Event.ticker_id == Ticker.id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date >= today,
            Event.event_date <= today + timedelta(days=14),
            Ticker.is_active.is_(True),
        )
        .order_by(Event.event_date, Ticker.symbol)
    )
    earnings_result = await db.execute(earnings_q)

    # Deduplicate: keep earliest earnings date per symbol
    tickers: dict[str, dict] = {}
    seen_earnings: set[str] = set()
    for r in earnings_result.all():
        if r.symbol not in seen_earnings:
            seen_earnings.add(r.symbol)
            days_until = (r.event_date - today).days
            score = max(0.0, 1.0 - days_until / 14.0)
            tickers[r.symbol] = {
                "name": r.name,
                "sector": r.sector,
                "industry": r.industry,
                "earnings_score": score,
                "reports_in_days": days_until,
                "reaction_score": 0.0,
                "recent_move_pct": None,
                "recent_outcome": None,
            }

    # ── Signal 2: recent reaction magnitude (last 10 days) with recency decay ─
    reaction_q = (
        select(
            Ticker.symbol,
            Ticker.name,
            Ticker.sector,
            Ticker.industry,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.pct_change_5d,
            HistoricalReaction.outcome,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.event_date >= today - timedelta(days=10),
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.is_active.is_(True),
            not_excluded(Ticker.symbol),
        )
        .order_by(HistoricalReaction.event_date.desc())
    )
    reaction_result = await db.execute(reaction_q)

    seen_reactions: set[str] = set()
    for r in reaction_result.all():
        if r.symbol not in seen_reactions:
            seen_reactions.add(r.symbol)
            move = float(r.pct_change_1d)
            days_ago = (today - r.event_date).days
            recency = 1.0 - 0.5 * (days_ago / 10.0)
            score = min(abs(move) / 10.0, 1.0) * recency
            move_5d = (
                round(float(r.pct_change_5d), 2)
                if r.pct_change_5d is not None
                else None
            )
            reaction_data = {
                "reaction_score": score,
                "recent_move_pct": round(move, 2),
                "recent_move_5d": move_5d,
                "recent_outcome": (
                    r.outcome.value if r.outcome else "unknown"
                ),
                "event_date": r.event_date.isoformat(),
            }
            if r.symbol in tickers:
                tickers[r.symbol].update(reaction_data)
            else:
                tickers[r.symbol] = {
                    "name": r.name,
                    "sector": r.sector,
                    "industry": r.industry,
                    "earnings_score": 0.0,
                    "reports_in_days": None,
                    **reaction_data,
                }

    # ── Signal 3: RV rank (elevated vol vs own history) ─────────────────────
    from app.services.rv_store import get_latest_rv_bulk

    from app.services.pending_deals import held_symbols
    for sym in await held_symbols(db):                 # a pending cash deal is never suggested (services/pending_deals)
        tickers.pop(sym, None)
    all_syms = list(tickers.keys())
    rv_rows = await get_latest_rv_bulk(db, all_syms) if all_syms else {}
    for sym, t in tickers.items():
        rv_row = rv_rows.get(sym)
        t["rv_score"] = float(rv_row.rv_rank) / 100.0 if rv_row is not None and rv_row.rv_rank is not None else 0.0

    # ── Score & rank ─────────────────────────────────────────────────────────
    scored = []
    for sym, t in tickers.items():
        catalyst = t["earnings_score"] + t["reaction_score"]
        if catalyst > 0:
            total = catalyst + 0.5 * t["rv_score"]
            scored.append((sym, t, total))

    scored.sort(key=lambda x: x[2], reverse=True)
    top = scored[:limit]

    # Batch intelligence for top picks only
    top_syms = [sym for sym, _, _ in top]
    cond_stats = await _batch_conditional_stats(db, top_syms)
    excluded = await excluded_symbols(db)        # such a card states the reason instead of an insight
    analyst_stats = await _batch_analyst_stats(db, top_syms)
    buy_share_stats = await _batch_buy_share_delta(db, top_syms)
    vol_data = await _batch_vol_regime(db, top_syms)
    base = await _get_base_rates(db)
    next_earnings = await _batch_next_earnings(db, top_syms)

    items = [
        SuggestionItem(
            symbol=sym,
            name=t["name"],
            sector=t.get("sector"),
            industry=t.get("industry"),
            score=round(total, 3),
            reports_in_days=t["reports_in_days"],
            recent_move_pct=t.get("recent_move_pct"),
            recent_move_5d=t.get("recent_move_5d"),
            recent_outcome=t.get("recent_outcome"),
            event_date=t.get("event_date"),
            insight=(EXCLUSION_REASON if sym in excluded else _suggestion_insight(
                cond_stats.get(sym), analyst_stats.get(sym),
                buy_share_stats.get(sym), base, sym,
            )[0]),
            vol_regime=vol_data.get(sym, {}).get("vol_regime"),
            iv_rv_note=vol_data.get(sym, {}).get("iv_rv_note"),
            **next_earnings.get(sym, {}),
        )
        for sym, t, total in top
    ]

    return SuggestionsResponse(items=items)


@router.get("/unusually-active", response_model=UnusuallyActiveResponse)
async def unusually_active(
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> UnusuallyActiveResponse:
    """Tickers with elevated realized volatility vs. their own history (rv_rank >= 85)."""
    max_date_result = await db.execute(
        sa.text("SELECT max(as_of_date) FROM rv_snapshots WHERE status = 'ok'")
    )
    latest_date = max_date_result.scalar()
    if latest_date is None or (date.today() - latest_date).days > 7:
        return UnusuallyActiveResponse(items=[])

    stmt = sa.text("""
        SELECT r.symbol, t.name, t.sector, t.industry, r.rv_rank, r.rv_20d
        FROM rv_snapshots r
        JOIN tickers t ON t.symbol = r.symbol AND t.is_active = true
        WHERE r.as_of_date = :latest_date
          AND r.symbol NOT IN (SELECT symbol FROM pending_deals WHERE status = 'active')   -- a pending cash deal leaves the tape
          AND r.status = 'ok'
          AND r.rv_rank >= :min_rank
        ORDER BY r.rv_rank DESC
        LIMIT :limit
    """)
    result = await db.execute(stmt, {"latest_date": latest_date, "limit": limit, "min_rank": DISCOVER_ELEVATED_RV})
    rows = result.all()

    symbols = [row.symbol for row in rows]
    vol_data = await _batch_vol_regime(db, symbols)
    next_earnings = await _batch_next_earnings(db, symbols)
    # a held rank stays on the tape, worded as the action that holds it ("Spun off Vylor on Oct 1, so its past year doesn't compare yet")

    items = [
        UnusuallyActiveItem(
            symbol=row.symbol,
            name=row.name,
            sector=row.sector,
            industry=row.industry,
            rv_rank=float(row.rv_rank),
            rv_20d=float(row.rv_20d),
            tier=discover_rv_tier(float(row.rv_rank)).label,
            insight=_unusually_active_insight(vol_data.get(row.symbol), row.symbol),
            vol_regime=vol_data.get(row.symbol, {}).get("vol_regime"),
            iv_rv_note=vol_data.get(row.symbol, {}).get("iv_rv_note"),
            iv_rv_spread_pp=vol_data.get(row.symbol, {}).get("iv_rv_spread_pp"),
            atm_iv=vol_data.get(row.symbol, {}).get("atm_iv"),
            iv_date=vol_data.get(row.symbol, {}).get("iv_date"),
            dominant_date=vol_data.get(row.symbol, {}).get("dominant_date"),
            dominant_move_pct=vol_data.get(row.symbol, {}).get("dominant_move_pct"),
            rank_hold_phrase=vol_data.get(row.symbol, {}).get("rank_hold_phrase"),
            rank_hold_reason=vol_data.get(row.symbol, {}).get("rv_rank_hold"),
            **next_earnings.get(row.symbol, {}),
        )
        for row in rows
    ]

    return UnusuallyActiveResponse(items=items)


@router.get("/latest-pick", response_model=LatestPickResponse)
async def latest_pick(
    db: AsyncSession = Depends(get_db),
    ledger_reader: bool = Depends(may_read_ledger),
) -> LatestPickResponse:
    """Most recent alert pick for the teaser strip."""
    if not LEDGER_PUBLIC and not ledger_reader:
        return LatestPickResponse(pick=None)
    from app.models.alert_pick import AlertPick

    stmt = (
        select(AlertPick)
        .where(
            AlertPick.source != "visitor",
            AlertPick.season == 2,
            AlertPick.status != "void",                  # a void pick is outside the record: never on Discover, never priced
            func.cast(AlertPick.generated_at, SADate) >= LEDGER_START,
        )
        .order_by(AlertPick.generated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    pick = result.scalar_one_or_none()
    if pick is None:
        return LatestPickResponse(pick=None)

    # Compute direction_hit and option pnl for closed picks
    direction_hit: bool | None = None
    option_pnl_pct: float | None = None
    current_price: float | None = None
    unrealized_move_pct: float | None = None
    price_as_of: str | None = None
    quote_reason: str | None = None

    entry = float(pick.entry_price) if pick.entry_price else None

    if pick.status == "closed" and pick.close_price is not None and entry:
        cp = float(pick.close_price)
        current_price = cp
        move = (cp - entry) / entry
        unrealized_move_pct = round(move * 100, 2)
        direction_hit = (
            move > 0 if pick.picked_direction == "bullish" else move < 0
        )
        # Option P&L for closed spreads
        if pick.suggested_strike and pick.cost_to_enter:
            strike = float(pick.suggested_strike)
            cost = float(pick.cost_to_enter)
            spread_strike = float(pick.suggested_spread_strike) if pick.suggested_spread_strike else None
            if pick.picked_direction == "bullish":
                intrinsic = max(cp - strike, 0)
            else:
                intrinsic = max(strike - cp, 0)
            if spread_strike:
                width = abs(strike - spread_strike)
                intrinsic = min(intrinsic, width)
            option_pnl_pct = pnl_percent(intrinsic - cost, cost)
    elif entry:
        # For open picks: the current price from Finnhub, shown only when its last trade is recent (price_freshness),
        # and dated by that trade
        try:
            from app.services import quote_cache
            from app.services.finnhub_client import FinnhubClient, VISITOR
            from app.services.price_freshness import assess_quote
            cached = quote_cache.get(pick.symbol)
            if cached is not None:
                cp, ts = cached.get("price"), cached.get("timestamp")
            else:
                finnhub = FinnhubClient(priority=VISITOR)
                try:
                    q = await finnhub.get_quote(pick.symbol)
                    cp = float(q.get("c") or 0) or None
                    ts = int(q["t"]) if q.get("t") else None
                    if cp:
                        change = float(q.get("d")) if q.get("d") is not None else None
                        change_pct = float(q.get("dp")) if q.get("dp") is not None else None
                        quote_cache.set(pick.symbol, {"price": cp, "change": change, "change_pct": change_pct, "timestamp": ts, "basis": q.get("basis", "last_trade")})
                finally:
                    await finnhub.close()
            state = assess_quote(cp, ts)
            if state.price is not None:
                current_price = round(state.price, 2)
                unrealized_move_pct = round((current_price - entry) / entry * 100, 2)
                price_as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            else:
                quote_reason = state.reason
        except Exception as exc:
            quote_reason = f"price unavailable ({type(exc).__name__})"

    return LatestPickResponse(
        pick=LatestPickItem(
            id=str(pick.id),
            symbol=pick.symbol,
            picked_direction=pick.picked_direction,
            strategy=pick.strategy,
            entry_price=float(pick.entry_price) if pick.entry_price else 0,
            current_price=current_price,
            unrealized_move_pct=unrealized_move_pct,
            price_as_of=price_as_of,
            quote_reason=quote_reason,
            status=pick.status,
            generated_at=pick.generated_at.isoformat() if pick.generated_at else "",
            expiration=pick.expiration,
            direction_hit=direction_hit,
            option_pnl_pct=option_pnl_pct,
        ),
    )


async def _batch_move_comparison(db: AsyncSession, rows, cond_stats: dict, today: date) -> dict[str, dict]:
    """Per symbol: the implied move from the freshest chain (its date the receipt) against the typical 1-day move over at least
    MIN_REPORTS stored reports, and the one-sentence comparison. A symbol missing either side gets no comparison."""
    from app.services import price_bars, quote_cache
    from app.services.briefing_build import _implied
    from app.services.earnings_calendar import level_of
    from app.services.implied_move import implied_move_allowed
    from app.services.move_comparison import MIN_REPORTS, compare_moves, comparison_sentence
    out: dict[str, dict] = {}
    for r in rows:
        if not implied_move_allowed(level_of(r.is_confirmed, getattr(r, "unresolved_since", None))):
            continue            # an estimated date is never priced
        cond = cond_stats.get(r.symbol)
        if not cond or (cond.get("total") or 0) < MIN_REPORTS or not cond.get("avg_abs_1d"):
            continue
        cached = quote_cache.get(r.symbol)
        spot = cached.get("price") if cached else None
        if spot is None:
            closes = await price_bars.bars(db, r.symbol, today - timedelta(days=14))
            spot = float(closes["Close"].iloc[-1]) if closes is not None and not closes.empty else None
        implied = await _implied(db, r.symbol, spot, r.event_date, today)
        if not implied:
            continue
        imp, typ = round(implied["implied_pct"] * 100, 1), round(float(cond["avg_abs_1d"]), 1)
        out[r.symbol] = {"implied_move_pct": imp, "chain_date": implied["chain_date"].isoformat(), "typical_move_pct": typ, "typical_n": int(cond["total"]),
                         "move_comparison": compare_moves(imp, typ), "comparison": comparison_sentence(imp, typ, implied["chain_date"])}
    return out


@router.get("/insight/{symbol}", response_model=InsightResponse)
async def ticker_insight(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> InsightResponse:
    """Single-ticker insight line using the suggestion insight generator."""
    upper = symbol.upper()
    # Verify ticker exists
    ticker_q = await db.execute(
        select(Ticker).where(Ticker.symbol == upper)
    )
    ticker = ticker_q.scalar_one_or_none()
    if ticker is None:
        return InsightResponse(insight=None)

    cond = await _batch_conditional_stats(db, [upper])
    buy_share = await _batch_buy_share_delta(db, [upper])
    base = await _get_base_rates(db)
    line, gen, _ = _suggestion_insight(
        cond.get(upper), None, buy_share.get(upper), base, upper,
    )
    rule = INSIGHT_GENERATOR_RULES.get(gen) if gen else None
    return InsightResponse(insight=line, rule=rule, as_of=insight_as_of(gen, cond.get(upper), buy_share.get(upper)))


def insight_as_of(gen: str | None, cond: dict | None, buy_share: dict | None) -> str | None:
    """The date the chosen generator's stat is as of: the buy-share line rests on the latest recommendation period,
    every other line on the newest earnings quarter in the sample."""
    if gen is None:
        return None
    src = buy_share if gen == "buy_delta" else cond
    return (src or {}).get("as_of")
