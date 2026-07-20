import statistics
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analyst_reaction_stats import AnalystReactionStats
from app.models.enums import EarningsOutcome, EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.schemas.historical_reaction import (
    AnalystReactionStatsRead,
    ConditionalEarningsRead,
    HistoricalReactionCreate,
    HistoricalReactionRead,
    ReactionSummaryRead,
)

router = APIRouter(prefix="/reactions", tags=["historical-reactions"])


# ── Per-row enrichment helper ──────────────────────────────────────────────────

def _enrich(r: HistoricalReaction) -> HistoricalReactionRead:
    """Convert ORM row to read schema, adding computed fields."""
    read = HistoricalReactionRead.model_validate(r)

    # EPS surprise % — skip when estimate is near zero (avoids misleading huge %)
    if r.eps_estimate is not None and r.eps_actual is not None:
        est = float(r.eps_estimate)
        if abs(est) > 0.01:
            read.eps_surprise_pct = round(
                (float(r.eps_actual) - est) / abs(est) * 100, 1
            )

    return read


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=ReactionSummaryRead)
async def get_reaction_summary(
    symbol: str = Query(..., description="Ticker symbol (e.g. AAPL)"),
    db: AsyncSession = Depends(get_db),
) -> ReactionSummaryRead:
    """Aggregate earnings-reaction insights: beat rate, beat-but-dropped, avg moves, sector comparison."""
    sym = symbol.upper()

    # 1. Ticker row (need sector)
    ticker = await db.scalar(select(Ticker).where(Ticker.symbol == sym))
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    # 2. All earnings reactions with a T+1 move recorded
    result = await db.execute(
        select(HistoricalReaction)
        .where(
            HistoricalReaction.ticker_id == ticker.id,
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.pct_change_1d.isnot(None),
        )
    )
    rows = list(result.scalars().all())

    total = len(rows)
    if total == 0:
        return ReactionSummaryRead(
            symbol=sym, sector=ticker.sector, total_quarters=0,
            beat_count=0, miss_count=0, meet_count=0, beat_rate_pct=0.0,
            beat_but_dropped_count=0, beat_but_dropped_rate_pct=None,
            avg_1d_on_beat=None, avg_1d_on_miss=None, avg_abs_1d=None,
            sector_avg_abs_1d=None, sector_peer_count=0,
        )

    beats  = [r for r in rows if r.outcome == EarningsOutcome.BEAT]
    misses = [r for r in rows if r.outcome == EarningsOutcome.MISS]
    meets  = [r for r in rows if r.outcome == EarningsOutcome.MEET]

    beat_dropped = [r for r in beats if float(r.pct_change_1d) < 0]

    beat_rate = round(len(beats) / total * 100, 1) if total else 0.0
    beat_dropped_rate = (
        round(len(beat_dropped) / len(beats) * 100, 1) if beats else None
    )

    all_1d  = [float(r.pct_change_1d) for r in rows]
    beat_1d = [float(r.pct_change_1d) for r in beats]
    miss_1d = [float(r.pct_change_1d) for r in misses]

    avg_abs_1d  = round(sum(abs(v) for v in all_1d)  / len(all_1d),  2)
    avg_1d_beat = round(sum(beat_1d) / len(beat_1d), 2) if beat_1d else None
    avg_1d_miss = round(sum(miss_1d) / len(miss_1d), 2) if miss_1d else None

    # 3. Sector peer comparison — only when we have a sector and ≥5 peer tickers
    sector_avg: float | None = None
    peer_count = 0

    if ticker.sector:
        peer_result = await db.execute(
            select(
                func.count(func.distinct(Ticker.id)).label("peer_tickers"),
                func.avg(func.abs(HistoricalReaction.pct_change_1d)).label("avg_abs"),
            )
            .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
            .where(
                Ticker.sector == ticker.sector,
                Ticker.symbol != sym,
                HistoricalReaction.event_type == EventType.EARNINGS,
                HistoricalReaction.pct_change_1d.isnot(None),
            )
        )
        peer_row = peer_result.one()
        peer_count = peer_row.peer_tickers or 0
        if peer_count >= 5 and peer_row.avg_abs is not None:
            sector_avg = round(float(peer_row.avg_abs), 2)

    return ReactionSummaryRead(
        symbol=sym,
        sector=ticker.sector,
        total_quarters=total,
        beat_count=len(beats),
        miss_count=len(misses),
        meet_count=len(meets),
        beat_rate_pct=beat_rate,
        beat_but_dropped_count=len(beat_dropped),
        beat_but_dropped_rate_pct=beat_dropped_rate,
        avg_1d_on_beat=avg_1d_beat,
        avg_1d_on_miss=avg_1d_miss,
        avg_abs_1d=avg_abs_1d,
        sector_avg_abs_1d=sector_avg,
        sector_peer_count=peer_count,
    )


# ── Conditional earnings intelligence ────────────────────────────────────────

MIN_QUARTERS = 8


def _continuation_stats(
    subset: list,
) -> tuple[float | None, float | None, int]:
    """Compute avg 5d move and continuation rate for a subset of reactions.

    Continuation = sign(pct_change_5d) matches sign(pct_change_1d).
    Returns (avg_5d, continuation_rate_pct, sample_size).
    """
    with_5d = [
        (float(r.pct_change_1d), float(r.pct_change_5d))
        for r in subset
        if r.pct_change_5d is not None
    ]
    if not with_5d:
        return None, None, 0
    avg_5d = round(sum(d5 for _, d5 in with_5d) / len(with_5d), 2)
    continued = sum(1 for d1, d5 in with_5d if (d1 >= 0) == (d5 >= 0))
    rate = round(continued / len(with_5d) * 100, 1)
    return avg_5d, rate, len(with_5d)


@router.get("/conditional", response_model=ConditionalEarningsRead)
async def get_conditional_earnings(
    symbol: str = Query(..., description="Ticker symbol (e.g. AAPL)"),
    db: AsyncSession = Depends(get_db),
) -> ConditionalEarningsRead:
    """Conditional earnings stats: beat/miss move profiles, follow-through, magnitude trend."""
    sym = symbol.upper()

    ticker = await db.scalar(select(Ticker).where(Ticker.symbol == sym))
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    result = await db.execute(
        select(HistoricalReaction)
        .where(
            HistoricalReaction.ticker_id == ticker.id,
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.pct_change_1d.isnot(None),
        )
        .order_by(HistoricalReaction.event_date.asc())
    )
    rows = list(result.scalars().all())
    total = len(rows)
    sufficient = total >= MIN_QUARTERS

    beats = [r for r in rows if r.outcome == EarningsOutcome.BEAT]
    misses = [r for r in rows if r.outcome == EarningsOutcome.MISS]
    meets = [r for r in rows if r.outcome == EarningsOutcome.MEET]
    unknowns = [r for r in rows if r.outcome not in (EarningsOutcome.BEAT, EarningsOutcome.MISS, EarningsOutcome.MEET)]

    # Insufficient history — return skeleton with counts only
    if not sufficient:
        return ConditionalEarningsRead(
            symbol=sym,
            total_quarters=total,
            has_sufficient_history=False,
            beat_count=len(beats), miss_count=len(misses),
            meet_count=len(meets), unknown_count=len(unknowns),
            avg_1d_on_beat=None, median_1d_on_beat=None,
            avg_1d_on_miss=None, median_1d_on_miss=None,
            beat_avg_5d=None, beat_continuation_rate_pct=None, beat_5d_sample=0,
            miss_avg_5d=None, miss_continuation_rate_pct=None, miss_5d_sample=0,
            recent_avg_abs_1d=None, prior_avg_abs_1d=None, magnitude_trend=None,
        )

    # ── Conditional 1d moves ─────────────────────────────────────────────────
    beat_1d = [float(r.pct_change_1d) for r in beats]
    miss_1d = [float(r.pct_change_1d) for r in misses]

    avg_1d_beat = round(sum(beat_1d) / len(beat_1d), 2) if beat_1d else None
    median_1d_beat = round(statistics.median(beat_1d), 2) if beat_1d else None
    avg_1d_miss = round(sum(miss_1d) / len(miss_1d), 2) if miss_1d else None
    median_1d_miss = round(statistics.median(miss_1d), 2) if miss_1d else None

    # ── Follow-through ───────────────────────────────────────────────────────
    beat_avg_5d, beat_cont, beat_5d_n = _continuation_stats(beats)
    miss_avg_5d, miss_cont, miss_5d_n = _continuation_stats(misses)

    # ── Magnitude trend: last 4 prints vs prior 4 ───────────────────────────
    abs_1d_all = [abs(float(r.pct_change_1d)) for r in rows]
    recent_4 = abs_1d_all[-4:]
    prior_4 = abs_1d_all[-8:-4] if total >= 8 else None

    recent_avg = round(sum(recent_4) / 4, 2) if len(recent_4) == 4 else None
    prior_avg = (
        round(sum(prior_4) / 4, 2)
        if prior_4 and len(prior_4) == 4
        else None
    )

    magnitude_trend: str | None = None
    if recent_avg is not None and prior_avg is not None:
        if prior_avg < 0.01:
            magnitude_trend = "stable"
        else:
            pct_change = (recent_avg - prior_avg) / prior_avg
            if pct_change > 0.20:
                magnitude_trend = "increasing"
            elif pct_change < -0.20:
                magnitude_trend = "decreasing"
            else:
                magnitude_trend = "stable"

    return ConditionalEarningsRead(
        symbol=sym,
        total_quarters=total,
        has_sufficient_history=sufficient,
        beat_count=len(beats),
        miss_count=len(misses),
        meet_count=len(meets),
        unknown_count=len(unknowns),
        avg_1d_on_beat=avg_1d_beat,
        median_1d_on_beat=median_1d_beat,
        avg_1d_on_miss=avg_1d_miss,
        median_1d_on_miss=median_1d_miss,
        beat_avg_5d=beat_avg_5d,
        beat_continuation_rate_pct=beat_cont,
        beat_5d_sample=beat_5d_n,
        miss_avg_5d=miss_avg_5d,
        miss_continuation_rate_pct=miss_cont,
        miss_5d_sample=miss_5d_n,
        recent_avg_abs_1d=recent_avg,
        prior_avg_abs_1d=prior_avg,
        magnitude_trend=magnitude_trend,
    )


@router.get("/analyst-stats", response_model=AnalystReactionStatsRead)
async def get_analyst_reaction_stats(
    symbol: str = Query(..., description="Ticker symbol (e.g. AAPL)"),
    db: AsyncSession = Depends(get_db),
) -> AnalystReactionStatsRead:
    """Precomputed stats: how does this stock react to analyst upgrades/downgrades?"""
    sym = symbol.upper()
    row = await db.scalar(
        select(AnalystReactionStats).where(AnalystReactionStats.symbol == sym)
    )
    if not row:
        raise HTTPException(status_code=404, detail="No analyst reaction stats for this ticker")
    return AnalystReactionStatsRead.model_validate(row)


@router.get("", response_model=list[HistoricalReactionRead])
async def list_reactions(
    symbol: str | None = Query(None, description="Filter by ticker symbol (e.g. AAPL)"),
    ticker_id: uuid.UUID | None = Query(None),
    event_type: EventType | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[HistoricalReactionRead]:
    q = select(HistoricalReaction).order_by(HistoricalReaction.event_date.desc())
    if symbol:
        ticker_id_sq = (
            select(Ticker.id).where(Ticker.symbol == symbol.upper()).scalar_subquery()
        )
        q = q.where(HistoricalReaction.ticker_id == ticker_id_sq)
    elif ticker_id:
        q = q.where(HistoricalReaction.ticker_id == ticker_id)
    if event_type:
        q = q.where(HistoricalReaction.event_type == event_type)
    result = await db.execute(q)
    return [_enrich(r) for r in result.scalars().all()]


@router.post("", response_model=HistoricalReactionRead, status_code=status.HTTP_201_CREATED)
async def create_reaction(
    payload: HistoricalReactionCreate,
    db: AsyncSession = Depends(get_db),
) -> HistoricalReactionRead:
    reaction = HistoricalReaction(**payload.model_dump())
    db.add(reaction)
    await db.commit()
    await db.refresh(reaction)
    return _enrich(reaction)


@router.get("/{reaction_id}", response_model=HistoricalReactionRead)
async def get_reaction(reaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> HistoricalReactionRead:
    r = await db.get(HistoricalReaction, reaction_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reaction not found")
    return _enrich(r)


@router.delete("/{reaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reaction(reaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    r = await db.get(HistoricalReaction, reaction_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reaction not found")
    await db.delete(r)
    await db.commit()
