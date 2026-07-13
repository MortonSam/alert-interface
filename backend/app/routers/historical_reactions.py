import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import EarningsOutcome, EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.schemas.historical_reaction import (
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
