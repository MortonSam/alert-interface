import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate, TickerRead, TickerUpdate

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("/", response_model=list[TickerRead])
async def list_tickers(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[TickerRead]:
    q = select(Ticker)
    if active_only:
        q = q.where(Ticker.is_active.is_(True))
    result = await db.execute(q.order_by(Ticker.symbol))
    tickers = list(result.scalars().all())

    # One extra query: next upcoming earnings date per ticker
    today = date.today()
    ned_q = (
        select(Event.ticker_id, func.min(Event.event_date).label("ned"))
        .where(Event.event_type == "earnings", Event.event_date >= today)
        .where(Event.ticker_id.isnot(None))
        .group_by(Event.ticker_id)
    )
    ned_rows = await db.execute(ned_q)
    ned_map: dict = {row.ticker_id: row.ned for row in ned_rows}

    enriched: list[TickerRead] = []
    for t in tickers:
        r = TickerRead.model_validate(t)
        r.next_earnings_date = ned_map.get(t.id)
        enriched.append(r)
    return enriched


@router.post("/", response_model=TickerRead, status_code=status.HTTP_201_CREATED)
async def create_ticker(payload: TickerCreate, db: AsyncSession = Depends(get_db)) -> Ticker:
    ticker = Ticker(**payload.model_dump())
    ticker.symbol = ticker.symbol.upper()
    db.add(ticker)
    await db.commit()
    await db.refresh(ticker)
    return ticker


@router.get("/{ticker_id}", response_model=TickerRead)
async def get_ticker(ticker_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Ticker:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.patch("/{ticker_id}", response_model=TickerRead)
async def update_ticker(
    ticker_id: uuid.UUID,
    payload: TickerUpdate,
    db: AsyncSession = Depends(get_db),
) -> Ticker:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticker, field, value)
    await db.commit()
    await db.refresh(ticker)
    return ticker


@router.delete("/{ticker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticker(ticker_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    ticker = await db.get(Ticker, ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    await db.delete(ticker)
    await db.commit()
