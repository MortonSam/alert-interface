import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.schemas.event import EventCreate, EventRead, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/upcoming", response_model=list[EventRead])
async def upcoming_events(
    symbol: str | None = Query(None, description="Filter by ticker symbol"),
    days: int = Query(60, ge=1, le=365, description="Look-ahead window in days"),
    event_type: EventType | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Event]:
    """Core catalyst-panel endpoint — upcoming events within the next N days."""
    today = date.today()
    cutoff = today + timedelta(days=days)

    q = (
        select(Event)
        .where(Event.event_date >= today, Event.event_date <= cutoff)
        .order_by(Event.event_date)
    )
    if symbol:
        q = q.join(Ticker, Event.ticker_id == Ticker.id).where(
            Ticker.symbol == symbol.upper()
        )
    if event_type:
        q = q.where(Event.event_type == event_type)

    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/", response_model=list[EventRead])
async def list_events(
    ticker_id: uuid.UUID | None = None,
    event_type: EventType | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Event]:
    q = select(Event).order_by(Event.event_date)
    if ticker_id:
        q = q.where(Event.ticker_id == ticker_id)
    if event_type:
        q = q.where(Event.event_type == event_type)
    if from_date:
        q = q.where(Event.event_date >= from_date)
    if to_date:
        q = q.where(Event.event_date <= to_date)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(payload: EventCreate, db: AsyncSession = Depends(get_db)) -> Event:
    data = payload.model_dump()
    # Map Pydantic alias back to column name
    data["metadata_"] = data.pop("metadata_", {})
    event = Event(**data)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.get("/{event_id}", response_model=EventRead)
async def get_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Event:
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    db: AsyncSession = Depends(get_db),
) -> Event:
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)
    await db.commit()
