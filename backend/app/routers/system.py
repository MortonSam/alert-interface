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
    last_refreshed_at: datetime | None          # written only when every data step of the nightly exited 0
    total_tickers: int
    total_reactions: int
    most_recent_reaction_date: date | None
    datasets: dict = {}                         # per dataset: at, ok, failed, steps (services/dataset_freshness)


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

    datasets: dict = {}
    try:
        import json as _json
        from app.models.system_metadata import SystemMetadata
        from app.services.dataset_freshness import dataset_ages
        raw = await get_value(db, "step_outcomes")
        rows = (await db.execute(select(SystemMetadata.key, SystemMetadata.value).where(SystemMetadata.key.like("step:%")))).all()
        stamps = {k.replace("step:", "").replace(":last_success", ""): v for k, v in rows}
        datasets = dataset_ages(_json.loads(raw) if raw else {}, stamps)
    except Exception:
        datasets = {}

    return SystemStatus(
        last_refreshed_at=last_refreshed_at,
        total_tickers=total_tickers,
        total_reactions=total_reactions,
        most_recent_reaction_date=most_recent_reaction_date,
        datasets=datasets,
    )


@router.get("/stats")
async def get_site_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Real counts behind the homepage counters. Nothing here is typed by hand."""
    from sqlalchemy import text
    from app.services.price_history_exclusion import EXCLUDED_SYMBOLS_SQL

    earnings_measured = await db.scalar(text(
        "SELECT count(*) FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id "
        "WHERE hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL AND t.symbol NOT IN " + EXCLUDED_SYMBOLS_SQL
    )) or 0
    analyst = (await db.execute(text(
        "SELECT count(*), min(event_date) FROM events WHERE event_type = 'analyst_action'"
    ))).one()
    return {
        "earnings_reports_measured": int(earnings_measured),
        "analyst_actions": int(analyst[0] or 0),
        "analyst_actions_since": analyst[1].isoformat() if analyst[1] else None,
    }
