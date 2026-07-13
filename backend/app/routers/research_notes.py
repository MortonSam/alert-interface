import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.research_note import ResearchNote
from app.schemas.research_note import (
    ResearchNoteGenerateRequest,
    ResearchNoteRead,
    ResearchNoteVerifyRequest,
)
from app.services.research_note_service import (
    get_research_note,
    run_research_note_background,
    start_research_note_generation,
    verify_existing_note,
)

router = APIRouter(prefix="/research-notes", tags=["research-notes"])


@router.post("/generate", response_model=ResearchNoteRead, status_code=201, dependencies=[Depends(require_admin)])
async def generate(
    payload: ResearchNoteGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ResearchNote:
    note = await start_research_note_generation(db, payload.ticker_id, payload.symbol)
    background_tasks.add_task(
        run_research_note_background,
        ticker_id=note.ticker_id,
        symbol=payload.symbol or "",
    )
    return note


@router.post("/verify", response_model=ResearchNoteRead, dependencies=[Depends(require_admin)])
async def verify(
    payload: ResearchNoteVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> ResearchNote:
    return await verify_existing_note(db, payload.ticker_id, payload.symbol)


@router.get("", response_model=ResearchNoteRead)
async def get_note(
    symbol: str | None = Query(None, description="Ticker symbol, e.g. AAPL"),
    ticker_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ResearchNote:
    if symbol is None and ticker_id is None:
        raise HTTPException(status_code=422, detail="Either symbol or ticker_id is required")
    note = await get_research_note(db, ticker_id, symbol)
    if note is None:
        raise HTTPException(status_code=404, detail="No research note found for this ticker")
    return note
