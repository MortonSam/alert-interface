import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.schemas.historical_reaction import HistoricalReactionCreate, HistoricalReactionRead

router = APIRouter(prefix="/reactions", tags=["historical-reactions"])


@router.get("/", response_model=list[HistoricalReactionRead])
async def list_reactions(
    ticker_id: uuid.UUID | None = None,
    event_type: EventType | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[HistoricalReaction]:
    q = select(HistoricalReaction).order_by(HistoricalReaction.event_date.desc())
    if ticker_id:
        q = q.where(HistoricalReaction.ticker_id == ticker_id)
    if event_type:
        q = q.where(HistoricalReaction.event_type == event_type)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/", response_model=HistoricalReactionRead, status_code=status.HTTP_201_CREATED)
async def create_reaction(
    payload: HistoricalReactionCreate,
    db: AsyncSession = Depends(get_db),
) -> HistoricalReaction:
    reaction = HistoricalReaction(**payload.model_dump())
    db.add(reaction)
    await db.commit()
    await db.refresh(reaction)
    return reaction


@router.get("/{reaction_id}", response_model=HistoricalReactionRead)
async def get_reaction(reaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> HistoricalReaction:
    r = await db.get(HistoricalReaction, reaction_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reaction not found")
    return r


@router.delete("/{reaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reaction(reaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    r = await db.get(HistoricalReaction, reaction_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reaction not found")
    await db.delete(r)
    await db.commit()
