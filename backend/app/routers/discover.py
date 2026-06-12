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


class SuggestionItem(BaseModel):
    symbol: str
    name: str | None
    score: float
    reports_in_days: int | None
    recent_move_pct: float | None
    recent_move_5d: float | None
    recent_outcome: str | None  # beat / miss / meet / unknown
    event_date: str | None  # ISO date of the reaction's report


class SuggestionsResponse(BaseModel):
    items: list[SuggestionItem]


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


@router.get("/suggestions", response_model=SuggestionsResponse)
async def suggestions(
    limit: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
) -> SuggestionsResponse:
    """Top tickers by convergence of cheap signals (no LLM, no external calls)."""
    today = date.today()

    # ── Signal 1: earnings proximity (next 14 days) ──────────────────────────
    earnings_q = (
        select(Ticker.symbol, Ticker.name, Event.event_date)
        .join(Event, Event.ticker_id == Ticker.id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.event_date >= today,
            Event.event_date <= today + timedelta(days=14),
            Ticker.is_active.is_(True),
        )
        .order_by(Event.event_date, Ticker.symbol)
    )
    earnings_result = await db.execute(earnings_q)

    # Deduplicate: keep earliest earnings date per symbol
    tickers: dict[str, dict] = {}
    seen_earnings: set[str] = set()
    for r in earnings_result.all():
        if r.symbol not in seen_earnings:
            seen_earnings.add(r.symbol)
            days_until = (r.event_date - today).days
            score = max(0.0, 1.0 - days_until / 14.0)
            tickers[r.symbol] = {
                "name": r.name,
                "earnings_score": score,
                "reports_in_days": days_until,
                "reaction_score": 0.0,
                "recent_move_pct": None,
                "recent_outcome": None,
            }

    # ── Signal 2: recent reaction magnitude (last 10 days) with recency decay ─
    reaction_q = (
        select(
            Ticker.symbol,
            Ticker.name,
            HistoricalReaction.event_date,
            HistoricalReaction.pct_change_1d,
            HistoricalReaction.pct_change_5d,
            HistoricalReaction.outcome,
        )
        .join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.event_date >= today - timedelta(days=10),
            HistoricalReaction.pct_change_1d.isnot(None),
            Ticker.is_active.is_(True),
        )
        .order_by(HistoricalReaction.event_date.desc())
    )
    reaction_result = await db.execute(reaction_q)

    seen_reactions: set[str] = set()
    for r in reaction_result.all():
        if r.symbol not in seen_reactions:
            seen_reactions.add(r.symbol)
            move = float(r.pct_change_1d)
            days_ago = (today - r.event_date).days
            recency = 1.0 - 0.5 * (days_ago / 10.0)
            score = min(abs(move) / 10.0, 1.0) * recency
            move_5d = (
                round(float(r.pct_change_5d), 2)
                if r.pct_change_5d is not None
                else None
            )
            reaction_data = {
                "reaction_score": score,
                "recent_move_pct": round(move, 2),
                "recent_move_5d": move_5d,
                "recent_outcome": (
                    r.outcome.value if r.outcome else "unknown"
                ),
                "event_date": r.event_date.isoformat(),
            }
            if r.symbol in tickers:
                tickers[r.symbol].update(reaction_data)
            else:
                tickers[r.symbol] = {
                    "name": r.name,
                    "earnings_score": 0.0,
                    "reports_in_days": None,
                    **reaction_data,
                }

    # ── Score & rank ─────────────────────────────────────────────────────────
    scored = []
    for sym, t in tickers.items():
        total = t["earnings_score"] + t["reaction_score"]
        if total > 0:
            scored.append((sym, t, total))

    scored.sort(key=lambda x: x[2], reverse=True)

    items = [
        SuggestionItem(
            symbol=sym,
            name=t["name"],
            score=round(total, 3),
            reports_in_days=t["reports_in_days"],
            recent_move_pct=t.get("recent_move_pct"),
            recent_move_5d=t.get("recent_move_5d"),
            recent_outcome=t.get("recent_outcome"),
            event_date=t.get("event_date"),
        )
        for sym, t, total in scored[:limit]
    ]

    return SuggestionsResponse(items=items)
