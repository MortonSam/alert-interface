from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.system_metadata_service import get_value

router = APIRouter(prefix="/system", tags=["system"])


class SystemStatus(BaseModel):
    last_refreshed_at: datetime | None
    total_tickers: int
    total_reactions: int
    most_recent_reaction_date: date | None


@router.get("/status", response_model=SystemStatus)
async def get_system_status(db: AsyncSession = Depends(get_db)) -> SystemStatus:
    last_refreshed_raw = await get_value(db, "last_refreshed_at")
    last_refreshed_at: datetime | None = None
    if last_refreshed_raw:
        try:
            last_refreshed_at = datetime.fromisoformat(last_refreshed_raw)
        except ValueError:
            pass

    total_tickers = await db.scalar(
        select(func.count()).select_from(Ticker).where(Ticker.is_active.is_(True))
    ) or 0

    total_reactions = await db.scalar(
        select(func.count()).select_from(HistoricalReaction)
    ) or 0

    most_recent_reaction_date: date | None = await db.scalar(
        select(func.max(HistoricalReaction.event_date))
    )

    return SystemStatus(
        last_refreshed_at=last_refreshed_at,
        total_tickers=total_tickers,
        total_reactions=total_reactions,
        most_recent_reaction_date=most_recent_reaction_date,
    )
