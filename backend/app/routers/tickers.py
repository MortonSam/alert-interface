import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate, TickerRead, TickerUpdate

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("/", response_model=list[TickerRead])
async def list_tickers(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[Ticker]:
    q = select(Ticker)
    if active_only:
        q = q.where(Ticker.is_active.is_(True))
    result = await db.execute(q.order_by(Ticker.symbol))
    return list(result.scalars().all())


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
