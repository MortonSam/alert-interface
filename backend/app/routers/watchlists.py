import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist, WatchlistTicker
from app.schemas.watchlist import WatchlistCreate, WatchlistRead, WatchlistTickerAdd, WatchlistUpdate

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def _load_items(q):
    return q.options(selectinload(Watchlist.items).selectinload(WatchlistTicker.ticker))


@router.get("/", response_model=list[WatchlistRead])
async def list_watchlists(db: AsyncSession = Depends(get_db)) -> list[Watchlist]:
    result = await db.execute(_load_items(select(Watchlist).order_by(Watchlist.name)))
    return list(result.scalars().all())


@router.post("/", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
async def create_watchlist(payload: WatchlistCreate, db: AsyncSession = Depends(get_db)) -> Watchlist:
    wl = Watchlist(**payload.model_dump())
    db.add(wl)
    await db.commit()
    result = await db.execute(_load_items(select(Watchlist).where(Watchlist.id == wl.id)))
    return result.scalar_one()


@router.get("/{watchlist_id}", response_model=WatchlistRead)
async def get_watchlist(watchlist_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Watchlist:
    result = await db.execute(_load_items(select(Watchlist).where(Watchlist.id == watchlist_id)))
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return wl


@router.patch("/{watchlist_id}", response_model=WatchlistRead)
async def update_watchlist(
    watchlist_id: uuid.UUID,
    payload: WatchlistUpdate,
    db: AsyncSession = Depends(get_db),
) -> Watchlist:
    wl = await db.get(Watchlist, watchlist_id)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wl, field, value)
    await db.commit()
    result = await db.execute(_load_items(select(Watchlist).where(Watchlist.id == watchlist_id)))
    return result.scalar_one()


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    wl = await db.get(Watchlist, watchlist_id)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    await db.delete(wl)
    await db.commit()


# ── Watchlist members ─────────────────────────────────────────────────────────

@router.post("/{watchlist_id}/tickers", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
async def add_ticker_to_watchlist(
    watchlist_id: uuid.UUID,
    payload: WatchlistTickerAdd,
    db: AsyncSession = Depends(get_db),
) -> Watchlist:
    wl = await db.get(Watchlist, watchlist_id)
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    ticker = await db.get(Ticker, payload.ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    item = WatchlistTicker(watchlist_id=watchlist_id, **payload.model_dump())
    db.add(item)
    await db.commit()
    result = await db.execute(_load_items(select(Watchlist).where(Watchlist.id == watchlist_id)))
    return result.scalar_one()


@router.delete("/{watchlist_id}/tickers/{ticker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_ticker_from_watchlist(
    watchlist_id: uuid.UUID,
    ticker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(WatchlistTicker).where(
            WatchlistTicker.watchlist_id == watchlist_id,
            WatchlistTicker.ticker_id == ticker_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ticker not in watchlist")
    await db.delete(item)
    await db.commit()
