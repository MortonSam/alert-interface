from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker

router = APIRouter(prefix="/discover", tags=["discover"])


# ── Response models ──────────────────────────────────────────────────────────


class ReportingSoonItem(BaseModel):
    symbol: str
    name: str | None
    earnings_date: str  # ISO date
    is_confirmed: bool


class ReportingSoonResponse(BaseModel):
    items: list[ReportingSoonItem]
    total: int


class JustReportedItem(BaseModel):
    symbol: str
    name: str | None
    event_date: str  # ISO date
    pct_change_1d: float | None
    outcome: str  # beat / miss / meet / unknown


class JustReportedResponse(BaseModel):
    items: list[JustReportedItem]
    total: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/reporting-soon", response_model=ReportingSoonResponse)
async def reporting_soon(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> ReportingSoonResponse:
    """Universe tickers with earnings in the next N days, soonest first."""
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

    # Deduplicate by symbol (keep earliest date, already sorted soonest-first)
    seen: set[str] = set()
    deduped = []
    for r in result.all():
        if r.symbol not in seen:
            seen.add(r.symbol)
            deduped.append(r)

    items = [
        ReportingSoonItem(
            symbol=r.symbol,
            name=r.name,
            earnings_date=r.event_date.isoformat(),
            is_confirmed=r.is_confirmed,
        )
        for r in deduped[:limit]
    ]

    return ReportingSoonResponse(items=items, total=len(deduped))


@router.get("/just-reported", response_model=JustReportedResponse)
async def just_reported(
    days: int = Query(5, ge=1, le=30),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> JustReportedResponse:
    """Universe tickers with a recent earnings reaction, most-recent first."""
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

    # Deduplicate by symbol (keep most-recent, already sorted desc)
    seen: set[str] = set()
    deduped = []
    for r in result.all():
        if r.symbol not in seen:
            seen.add(r.symbol)
            deduped.append(r)

    items = [
        JustReportedItem(
            symbol=r.symbol,
            name=r.name,
            event_date=r.event_date.isoformat(),
            pct_change_1d=round(float(r.pct_change_1d), 2) if r.pct_change_1d is not None else None,
            outcome=r.outcome.value if r.outcome else "unknown",
        )
        for r in deduped[:limit]
    ]

    return JustReportedResponse(items=items, total=len(deduped))
