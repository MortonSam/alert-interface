import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.research_note import ResearchNote
from app.schemas.research_note import ResearchNoteGenerateRequest, ResearchNoteRead
from app.services.research_note_service import generate_research_note, get_research_note

router = APIRouter(prefix="/research-notes", tags=["research-notes"])


@router.post("/generate", response_model=ResearchNoteRead, status_code=201)
async def generate(
    payload: ResearchNoteGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ResearchNote:
    return await generate_research_note(db, payload.ticker_id, payload.symbol)


@router.get("/", response_model=ResearchNoteRead)
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
