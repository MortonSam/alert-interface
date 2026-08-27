from __future__ import annotations

import math
from datetime import date, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker

router = APIRouter(prefix="/discover", tags=["discover"])

# Minimum quarters for conditional earnings insight lines
_MIN_QUARTERS = 4


# ── Response models ──────────────────────────────────────────────────────────


class ReportingSoonItem(BaseModel):
    symbol: str
    name: str | None
    earnings_date: str  # ISO date
    is_confirmed: bool
    insight: str | None = None  # e.g. "Beat 18 of 20 — beats largely priced in"
    vol_regime: str | None = None  # "iv_rich" | "iv_cheap" | None


class ReportingSoonResponse(BaseModel):
    items: list[ReportingSoonItem]
    total: int


class SuggestionItem(BaseModel):
    symbol: str
    name: str | None
    score: float
    reports_in_days: int | None
    recent_move_pct: float | None
    recent_move_5d: float | None
    recent_outcome: str | None  # beat / miss / meet / unknown
    event_date: str | None  # ISO date of the reaction's report
    insight: str | None = None
    vol_regime: str | None = None


class SuggestionsResponse(BaseModel):
    items: list[SuggestionItem]


class JustReportedItem(BaseModel):
    symbol: str
    name: str | None
    event_date: str  # ISO date
    pct_change_1d: float | None
    outcome: str  # beat / miss / meet / unknown
    insight: str | None = None  # e.g. "Moved -6.3% vs +2.7% typical beat"
    vol_regime: str | None = None


class JustReportedResponse(BaseModel):
    items: list[JustReportedItem]
    total: int


class UnusuallyActiveItem(BaseModel):
    symbol: str
    name: str | None
    rv_rank: float
    rv_20d: float
    tier: str  # "extreme" or "elevated"
    insight: str | None = None  # e.g. "IV rich +12pp — options expensive vs realized"
    vol_regime: str | None = None


class UnusuallyActiveResponse(BaseModel):
    items: list[UnusuallyActiveItem]


class LatestPickItem(BaseModel):
    id: str
    symbol: str
    picked_direction: str
    strategy: str | None
    entry_price: float
    current_price: float | None
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
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.symbol.in_(symbols),
        )
        .order_by(HistoricalReaction.event_date.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Aggregate per symbol
    by_sym: dict[str, list[tuple]] = {}
    for r in rows:
        by_sym.setdefault(r.symbol, []).append((r.outcome, float(r.pct_change_1d)))

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
            "total": total,
            "beat_count": beat_count,
            "miss_count": miss_count,
            "bbd_count": bbd,
            "avg_1d_on_beat": avg_1d_on_beat,
            "avg_1d_on_miss": avg_1d_on_miss,
            "avg_abs_1d": avg_abs_1d,
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
    iv_stmt = sa.text("""
        SELECT DISTINCT ON (symbol) symbol, atm_iv, date
        FROM iv_history
        WHERE symbol = ANY(:syms)
        ORDER BY symbol, date DESC
    """)
    iv_result = await db.execute(iv_stmt, {"syms": symbols})
    iv_map: dict[str, float] = {}
    iv_dates: dict[str, date] = {}
    for r in iv_result.all():
        if r.atm_iv is not None:
            iv_map[r.symbol] = float(r.atm_iv)
            iv_dates[r.symbol] = r.date

    # Latest RV per symbol
    from app.services.rv_store import get_latest_rv_bulk
    rv_rows = await get_latest_rv_bulk(db, symbols)

    today = date.today()
    out: dict[str, dict] = {}
    for sym in symbols:
        atm_iv = iv_map.get(sym)
        rv_row = rv_rows.get(sym)
        rv_20d = float(rv_row.rv_20d) if rv_row and rv_row.rv_20d else None
        rv_rank = float(rv_row.rv_rank) if rv_row and rv_row.rv_rank else None

        # Only compute spread if IV data is fresh (<= 5 calendar days)
        iv_date = iv_dates.get(sym)
        if atm_iv is not None and iv_date and (today - iv_date).days > 5:
            atm_iv = None  # stale IV, skip

        if atm_iv is not None and rv_20d is not None and rv_20d > 0:
            spread_pp = round((atm_iv - rv_20d) * 100, 1)
            if spread_pp > 8:
                regime = "iv_rich"
            elif spread_pp < -4:
                regime = "iv_cheap"
            else:
                regime = None  # "iv_fair" — no chip
        else:
            spread_pp = None
            regime = None

        out[sym] = {
            "iv_rv_spread_pp": spread_pp,
            "vol_regime": regime,
            "atm_iv": atm_iv,
            "rv_20d": rv_20d,
            "rv_rank": rv_rank,
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
        WHERE symbol = ANY(:syms)
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

    out: dict[str, dict] = {}
    for sym, rows in by_ticker.items():
        if not rows:
            continue
        latest = rows[0]
        earlier = None
        for r in rows:
            if (latest.period - r.period).days >= 60:
                earlier = r
                break

        def bs(r):
            tot = r.strong_buy + r.buy + r.hold + r.sell + r.strong_sell
            return ((r.strong_buy + r.buy) / tot, tot) if tot else (0, 0)

        ls, lt = bs(latest)
        if earlier is None or lt < 5:
            continue
        es, et = bs(earlier)
        if et < 5:
            continue
        out[sym] = {"buy_share": ls, "delta": ls - es, "total": lt}

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

    def _stats(vals: list[float]) -> tuple[float, float]:
        if len(vals) < 3:
            return (0.0, 1.0)
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


def _sym_variant(symbol: str, n: int) -> int:
    """Deterministic variant index from symbol hash — stable per ticker."""
    return sum(ord(c) for c in symbol) % n


def _reporting_soon_insight(cond: dict | None, symbol: str = "") -> str | None:
    """Build insight for a Reporting Soon card from conditional earnings stats."""
    if not cond or cond["total"] < _MIN_QUARTERS:
        return None

    total = cond["total"]
    beat_count = cond["beat_count"]
    bbd = cond["bbd_count"]
    v = _sym_variant(symbol, 3)

    if beat_count >= 3:
        beat_rate = beat_count / total
        if bbd >= 2 and beat_count >= 4:
            bbd_pct = round(bbd / beat_count * 100)
            templates = [
                f"Beat {beat_count} of {total}, but {bbd_pct}% of beats dropped",
                f"{beat_count}/{total} beats but stock fell {bbd_pct}% of the time",
                f"Beats in {beat_count} of {total}q, yet {bbd_pct}% sold off anyway",
            ]
            return templates[v]
        if beat_rate >= 0.75:
            avg = cond["avg_1d_on_beat"]
            if avg is not None:
                sign = "+" if avg >= 0 else ""
                templates = [
                    f"Beat {beat_count} of {total} with avg {sign}{avg:.1f}% on beats",
                    f"{beat_count}/{total} beats, typically {sign}{avg:.1f}% next day",
                    f"Topped estimates {beat_count} of {total}q, avg {sign}{avg:.1f}% reaction",
                ]
                return templates[v]
            return f"Beat {beat_count} of {total}"

    avg_abs = cond["avg_abs_1d"]
    if avg_abs is not None:
        templates = [
            f"Avg move {chr(0xB1)}{avg_abs:.1f}% on earnings ({total}q)",
            f"Typically swings {chr(0xB1)}{avg_abs:.1f}% around earnings ({total}q)",
            f"Earnings move averages {chr(0xB1)}{avg_abs:.1f}% over {total} quarters",
        ]
        return templates[v]

    return None


def _just_reported_insight(
    pct_1d: float | None, outcome: str, cond: dict | None, symbol: str = "",
) -> str | None:
    """Build insight for a Just Reported card: realized vs typical."""
    if pct_1d is None:
        return None
    if not cond or cond["total"] < _MIN_QUARTERS:
        return None

    avg_abs = cond["avg_abs_1d"]
    if avg_abs is None:
        return None

    sign = "+" if pct_1d >= 0 else ""
    move_str = f"{sign}{pct_1d:.1f}%"
    v = _sym_variant(symbol, 3)

    if outcome in ("beat", "miss"):
        key = "avg_1d_on_beat" if outcome == "beat" else "avg_1d_on_miss"
        typical = cond.get(key)
        if typical is not None:
            t_sign = "+" if typical >= 0 else ""
            templates = [
                f"Moved {move_str} vs {t_sign}{typical:.1f}% typical {outcome}",
                f"{move_str} reaction, {outcome}s average {t_sign}{typical:.1f}%",
                f"Reacted {move_str} (typical {outcome}: {t_sign}{typical:.1f}%)",
            ]
            return templates[v]

    templates = [
        f"Moved {move_str} vs {chr(0xB1)}{avg_abs:.1f}% typical",
        f"{move_str} post-earnings, avg swing is {chr(0xB1)}{avg_abs:.1f}%",
        f"Reacted {move_str} against a {chr(0xB1)}{avg_abs:.1f}% typical move",
    ]
    return templates[v]


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

    # ── Generator: beat_rate ─────────────────────────────────────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond["beat_count"] > 0:
        beat_rate = cond["beat_count"] / cond["total"]
        br = base.get("beat_rate", {})
        z = abs(beat_rate - br.get("med", 0)) / br.get("sd", 1)
        pct = round(beat_rate * 100)
        med_pct = round(br.get("med", 0) * 100)
        candidates.append((
            f"Beats estimates {pct}% of the time, versus {med_pct}% across the S&P",
            z, "beat_rate",
        ))

    # ── Generator: priced_in (beat-but-dropped rate) ─────────────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond["beat_count"] >= 4 and cond["bbd_count"] >= 2:
        bbd_rate = cond["bbd_count"] / cond["beat_count"]
        bb = base.get("bbd_rate", {})
        z = abs(bbd_rate - bb.get("med", 0)) / bb.get("sd", 1)
        pct = round(bbd_rate * 100)
        med_pct = round(bb.get("med", 0) * 100)
        candidates.append((
            f"Sells off after {pct}% of beats, versus {med_pct}% across the S&P",
            z, "priced_in",
        ))

    # ── Generator: avg_move (average absolute earnings move) ─────────────────
    if cond and cond["total"] >= _MIN_QUARTERS and cond.get("avg_abs_1d") is not None:
        avg = cond["avg_abs_1d"]
        am = base.get("avg_abs_move", {})
        z = abs(avg - am.get("med", 0)) / am.get("sd", 1)
        med = am.get("med", 0)
        if med > 0 and avg >= med * 1.8:
            ratio = f"{avg / med:.1f}x the index median"
        else:
            ratio = f"versus {chr(0xB1)}{med:.1f}% across the S&P"
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
            mr = base.get("miss_ratio", {})
            z = abs(ratio - mr.get("med", 0)) / mr.get("sd", 1)
            candidates.append((
                f"Misses cost {abs(avg_miss):.1f}% avg vs +{abs(avg_beat):.1f}% on beats",
                z, "miss_skew",
            ))

    # ── Generator: buy_delta (analyst buy-share shift) ───────────────────────
    if buy_share:
        delta = buy_share["delta"]
        share = buy_share["buy_share"]
        total = buy_share["total"]
        bd = base.get("buy_delta", {})
        z = abs(delta - bd.get("med", 0)) / bd.get("sd", 1)
        share_pct = round(share * 100)
        if delta >= 0:
            candidates.append((
                f"Buy share {share_pct}% of {total} analysts, up {abs(delta):.0%} in 3 months",
                z, "buy_delta",
            ))
        else:
            candidates.append((
                f"Buy share {share_pct}% of {total} analysts, down {abs(delta):.0%} in 3 months",
                z, "buy_delta",
            ))

    if not candidates:
        return None, None, 0.0

    # Pick the highest |z|; ties fall back to insertion order (old priority)
    candidates.sort(key=lambda x: -x[1])
    line, z, gen = candidates[0]

    # If best |z| < 0.5, fall back to priority order (first candidate added)
    if z < 0.5:
        line, z, gen = candidates[0]  # already sorted, but use first-added as tiebreak
        # Re-sort to original insertion order for sub-0.5 ties
        for orig_line, orig_z, orig_gen in candidates:
            line, z, gen = orig_line, orig_z, orig_gen
            break

    return line, gen, z


def _unusually_active_insight(vol: dict | None, symbol: str = "") -> str | None:
    """Build insight for Unusually Active: IV-RV context."""
    if not vol:
        return None
    spread = vol.get("iv_rv_spread_pp")
    regime = vol.get("vol_regime")
    rv_rank = vol.get("rv_rank")
    v = _sym_variant(symbol, 3)

    if spread is not None and rv_rank is not None:
        label = ""
        if regime == "iv_rich":
            label = "IV rich"
        elif regime == "iv_cheap":
            label = "IV cheap"

        sign = "+" if spread >= 0 else ""
        if label:
            templates = [
                f"{label} at {sign}{spread:.0f}pp spread, RV rank {rv_rank:.0f}",
                f"{label}: {sign}{spread:.0f}pp vs realized, rank {rv_rank:.0f}",
                f"Options {label.lower()} ({sign}{spread:.0f}pp), RV rank {rv_rank:.0f}",
            ]
            return templates[v]
        templates = [
            f"IV-RV spread {sign}{spread:.0f}pp, RV rank {rv_rank:.0f}",
            f"IV {sign}{spread:.0f}pp vs realized, rank {rv_rank:.0f}",
            f"Implied-realized gap {sign}{spread:.0f}pp, RV rank {rv_rank:.0f}",
        ]
        return templates[v]

    if rv_rank is not None:
        return f"RV rank {rv_rank:.0f}"

    return None


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
        select(Ticker.symbol, Ticker.name, Event.event_date, Event.is_confirmed)
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
            earnings_date=r.event_date.isoformat(),
            is_confirmed=r.is_confirmed,
            insight=_reporting_soon_insight(cond, r.symbol),
            vol_regime=vol["vol_regime"] if vol else None,
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
            event_date=r.event_date.isoformat(),
            pct_change_1d=round(pct, 2) if pct else None,
            outcome=outcome,
            insight=_just_reported_insight(pct, outcome, cond, r.symbol),
            vol_regime=vol["vol_regime"] if vol else None,
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
        select(Ticker.symbol, Ticker.name, Event.event_date)
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
                    "earnings_score": 0.0,
                    "reports_in_days": None,
                    **reaction_data,
                }

    # ── Signal 3: RV rank (elevated vol vs own history) ─────────────────────
    from app.services.rv_store import get_latest_rv_bulk

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
    analyst_stats = await _batch_analyst_stats(db, top_syms)
    buy_share_stats = await _batch_buy_share_delta(db, top_syms)
    vol_data = await _batch_vol_regime(db, top_syms)
    base = await _get_base_rates(db)

    items = [
        SuggestionItem(
            symbol=sym,
            name=t["name"],
            score=round(total, 3),
            reports_in_days=t["reports_in_days"],
            recent_move_pct=t.get("recent_move_pct"),
            recent_move_5d=t.get("recent_move_5d"),
            recent_outcome=t.get("recent_outcome"),
            event_date=t.get("event_date"),
            insight=_suggestion_insight(
                cond_stats.get(sym), analyst_stats.get(sym),
                buy_share_stats.get(sym), base, sym,
            )[0],
            vol_regime=vol_data.get(sym, {}).get("vol_regime"),
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
        SELECT r.symbol, t.name, r.rv_rank, r.rv_20d
        FROM rv_snapshots r
        JOIN tickers t ON t.symbol = r.symbol AND t.is_active = true
        WHERE r.as_of_date = :latest_date
          AND r.status = 'ok'
          AND r.rv_rank >= 85
        ORDER BY r.rv_rank DESC
        LIMIT :limit
    """)
    result = await db.execute(stmt, {"latest_date": latest_date, "limit": limit})
    rows = result.all()

    symbols = [row.symbol for row in rows]
    vol_data = await _batch_vol_regime(db, symbols)

    items = [
        UnusuallyActiveItem(
            symbol=row.symbol,
            name=row.name,
            rv_rank=float(row.rv_rank),
            rv_20d=float(row.rv_20d),
            tier="extreme" if float(row.rv_rank) >= 93 else "elevated",
            insight=_unusually_active_insight(vol_data.get(row.symbol), row.symbol),
            vol_regime=vol_data.get(row.symbol, {}).get("vol_regime"),
        )
        for row in rows
    ]

    return UnusuallyActiveResponse(items=items)


@router.get("/latest-pick", response_model=LatestPickResponse)
async def latest_pick(
    db: AsyncSession = Depends(get_db),
) -> LatestPickResponse:
    """Most recent alert pick for the teaser strip. No auth required."""
    from app.models.alert_pick import AlertPick

    stmt = (
        select(AlertPick)
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
            if cost > 0:
                option_pnl_pct = round((intrinsic - cost) / cost * 100, 1)
    elif entry:
        # For open picks: try to get current price from Finnhub
        try:
            from app.services import quote_cache
            from app.services.finnhub_client import FinnhubClient
            cached = quote_cache.get(pick.symbol)
            if cached is not None:
                cp = cached.get("price")
            else:
                finnhub = FinnhubClient()
                try:
                    q = await finnhub.get_quote(pick.symbol)
                    cp = float(q.get("c") or 0) or None
                    if cp:
                        change = float(q.get("d")) if q.get("d") is not None else None
                        change_pct = float(q.get("dp")) if q.get("dp") is not None else None
                        quote_cache.set(pick.symbol, {"price": cp, "change": change, "change_pct": change_pct})
                finally:
                    await finnhub.close()
            if cp:
                current_price = round(cp, 2)
                unrealized_move_pct = round(
                    (current_price - entry) / entry * 100, 2,
                )
        except Exception:
            pass

    return LatestPickResponse(
        pick=LatestPickItem(
            id=str(pick.id),
            symbol=pick.symbol,
            picked_direction=pick.picked_direction,
            strategy=pick.strategy,
            entry_price=float(pick.entry_price) if pick.entry_price else 0,
            current_price=current_price,
            unrealized_move_pct=unrealized_move_pct,
            status=pick.status,
            generated_at=pick.generated_at.isoformat() if pick.generated_at else "",
            expiration=pick.expiration,
            direction_hit=direction_hit,
            option_pnl_pct=option_pnl_pct,
        ),
    )
