import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_draft_caller, is_admin, require_admin
from app.database import get_db
from app.models.research_note import ResearchNote
from app.models.ticker import Ticker
from app.schemas.research_note import LatestVerifiedNoteRead
from app.services.note_currency import report_since
from sqlalchemy import select
from app.schemas.research_note import (
    ResearchNoteGenerateRequest,
    ResearchNoteRead,
    ResearchNoteVerifyRequest,
)
from app.services.draft_limiter import RESEARCH_GENERATION_POLICY, check_limit, get_client_ip, record_use
from app.services.research_note_service import (
    _resolve_ticker,
    get_research_note,
    is_verified,
    run_research_note_background,
    start_research_note_generation,
    verification_failed,
    verify_existing_note,
)

router = APIRouter(prefix="/research-notes", tags=["research-notes"])

# ── Who may generate ──────────────────────────────────────────────────────────
#
# Anyone, within RESEARCH_GENERATION_POLICY (per-IP hour and day limits, a site-wide
# daily cap the owner does not skip), unless PUBLIC_RESEARCH_GENERATION is false: then
# only the owner. The flag is read from the environment on every request, so flipping
# the Railway variable is enough.

OWNER_ONLY_MESSAGE = "Note generation is currently limited to the site owner"
NOTE_EXISTS_MESSAGE = "A note for this ticker already exists; only the site owner can regenerate it"
NOTE_UNPUBLISHED_MESSAGE = "A note for this ticker exists but did not pass verification; only the site owner can regenerate it"
EXPECTED_WAIT_SECONDS = (30, 60)   # what the page tells a visitor while a note generates
FALSE_VALUES = {"0", "false", "no", "off"}


def public_generation_enabled() -> bool:
    return os.environ.get("PUBLIC_RESEARCH_GENERATION", "true").strip().lower() not in FALSE_VALUES


def generation_policy(admin: bool) -> dict:
    public = public_generation_enabled()
    return {
        "public": public,
        "can_generate": public or admin,          # a first note for a ticker that has none
        "can_regenerate": admin,                  # replacing a note that exists, whatever its state
        "owner_only_message": None if public else OWNER_ONLY_MESSAGE,
        "per_ip_hour": RESEARCH_GENERATION_POLICY.per_ip_hour,
        "per_ip_day": RESEARCH_GENERATION_POLICY.per_ip_day,
        "site_daily_cap": RESEARCH_GENERATION_POLICY.global_day,
        "expected_wait_seconds": list(EXPECTED_WAIT_SECONDS),
    }


@router.get("/policy")
async def get_generation_policy(admin: bool = Depends(is_admin)) -> dict:
    """The rules the Research section renders: who may generate, the limits, the expected wait."""
    return generation_policy(admin)


def _has_note_from_today(note: ResearchNote, now: datetime) -> bool:
    """One note per ticker per day: a note in progress, or one completed today, is the note."""
    if note.status in ("generating", "verifying"):
        return True
    if note.status != "complete":
        return False   # failed or verification_failed: the ticker has no note, generate again
    generated = note.generated_at if note.generated_at.tzinfo else note.generated_at.replace(tzinfo=timezone.utc)
    return generated.astimezone(timezone.utc).date() == now.date()


@router.post("/generate", response_model=ResearchNoteRead, status_code=201)
async def generate(
    payload: ResearchNoteGenerateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    force: bool = Query(False, description="Owner only: regenerate a note that exists from today"),
    db: AsyncSession = Depends(get_db),
    caller: str = Depends(get_draft_caller),
    admin: bool = Depends(is_admin),
) -> ResearchNoteRead:
    if not admin and not public_generation_enabled():
        raise HTTPException(status_code=403, detail=OWNER_ONLY_MESSAGE)

    ticker = await _resolve_ticker(db, payload.ticker_id, payload.symbol)
    now = datetime.now(timezone.utc)
    existing = await get_research_note(db, ticker.id, None)
    if existing is not None and existing.status != "failed" and not admin:
        # a visitor generates only where no note exists: a completed note (from any day), one in progress or one
        # that did not pass verification is the owner's to replace. A failed generation produced no note, so the
        # visitor may try again. Nothing generated, nothing charged here.
        if verification_failed(existing):
            raise HTTPException(status_code=409, detail=NOTE_UNPUBLISHED_MESSAGE)
        response.status_code = 200
        return await note_for_reader(db, existing, admin)
    if existing is not None and _has_note_from_today(existing, now) and not force:
        response.status_code = 200   # the owner without force: today's note is returned
        return await note_for_reader(db, existing, admin)

    client_ip = get_client_ip(request)
    await check_limit(db, RESEARCH_GENERATION_POLICY, caller, client_ip)
    note = await start_research_note_generation(db, ticker.id, None)
    charged_at = await record_use(db, RESEARCH_GENERATION_POLICY, caller, client_ip, ticker.symbol)
    background_tasks.add_task(
        run_research_note_background,
        ticker_id=note.ticker_id,
        symbol=ticker.symbol,
        charge={"ip": client_ip, "at": charged_at},
    )
    return await note_for_reader(db, note, admin)


@router.post("/verify", response_model=ResearchNoteRead, dependencies=[Depends(require_admin)])
async def verify(
    payload: ResearchNoteVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> ResearchNote:
    return await verify_existing_note(db, payload.ticker_id, payload.symbol)


def _note_for_reader(note: ResearchNote, admin: bool) -> ResearchNoteRead:
    """What this reader may see of a note.

    Visitors only ever get the text of a note whose verification completed. A
    note whose verification failed does not exist for them (404). While a note
    is generating or being verified they get its status with the text withheld.
    Admins get everything, with verification_failed set so the page can say so.
    """
    failed = verification_failed(note)
    read = ResearchNoteRead.model_validate(note)
    if admin:
        return read.model_copy(update={"verification_failed": failed})
    if failed:
        raise HTTPException(status_code=404, detail="No research note found for this ticker")
    if not is_verified(note):
        return read.model_copy(update={
            "content": "", "structured_content": None, "verification": None,
            "error": visitor_failure_reason(note) if note.status == "failed" else None,
        })
    return read


async def note_for_reader(db, note: ResearchNote, admin: bool) -> ResearchNoteRead:
    """_note_for_reader, plus the date the company reported again after the note was written (None while it is current)."""
    read = _note_for_reader(note, admin)
    return read.model_copy(update={"report_since": await report_since(db, note.ticker_id, note.generated_at)})


def visitor_failure_reason(note: ResearchNote) -> str:
    """Why a failed generation produced nothing, in a sentence without the exception text."""
    if note.error and "timed out" in note.error.lower():
        return "Generation timed out before a note was produced. Your limit was not charged."
    return "Generation failed before a note was produced. Your limit was not charged."


@router.get("/latest-verified", response_model=LatestVerifiedNoteRead)
async def latest_verified(db: AsyncSession = Depends(get_db)) -> LatestVerifiedNoteRead:
    """The most recently verified complete note on an active ticker whose company has not reported since it was written, for the
    home page. A note written before its company's latest report is never shown there as current; 404 when no note qualifies (the
    home page then hides the section)."""
    rows = (await db.execute(
        select(ResearchNote, Ticker.symbol, Ticker.name)
        .join(Ticker, Ticker.id == ResearchNote.ticker_id)
        .where(ResearchNote.status == "complete", ResearchNote.verification.is_not(None), Ticker.is_active.is_(True))
        .order_by(ResearchNote.verified_at.desc().nulls_last(), ResearchNote.generated_at.desc())
        .limit(200)
    )).all()
    row = None
    for candidate in rows:
        if is_verified(candidate[0]) and await report_since(db, candidate[0].ticker_id, candidate[0].generated_at) is None:
            row = candidate
            break
    if row is None:
        raise HTTPException(status_code=404, detail="No current verified research note")
    note, symbol, name = row
    sc = note.structured_content or {}
    return LatestVerifiedNoteRead(
        symbol=symbol, company_name=name, generated_at=note.generated_at, verified_at=note.verified_at,
        rating=sc.get("rating"), stats=sc.get("stats"), highlights=list(sc.get("highlights") or [])[:2],
        verification_summary=(note.verification or {}).get("summary"),
    )


@router.get("", response_model=ResearchNoteRead)
async def get_note(
    symbol: str | None = Query(None, description="Ticker symbol, e.g. AAPL"),
    ticker_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: bool = Depends(is_admin),
) -> ResearchNoteRead:
    if symbol is None and ticker_id is None:
        raise HTTPException(status_code=422, detail="Either symbol or ticker_id is required")
    note = await get_research_note(db, ticker_id, symbol)
    if note is None:
        raise HTTPException(status_code=404, detail="No research note found for this ticker")
    return await note_for_reader(db, note, admin)


class StalenessRead(BaseModel):
    stale: bool
    reason: str | None = None


STALENESS_DAYS = 30


CURRENT_REACTION_VERSION = 3


@router.get("/staleness/{symbol}", response_model=StalenessRead)
async def check_staleness(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> StalenessRead:
    """Check if a research note is stale (generated >30 days ago or before reaction-window correction). DB only."""
    note = await get_research_note(db, None, symbol.upper())
    if note is None:
        return StalenessRead(stale=False, reason=None)
    if note.generated_at is None:
        return StalenessRead(stale=False, reason=None)
    # Check data version staleness first (more actionable)
    if note.data_version < CURRENT_REACTION_VERSION:
        return StalenessRead(stale=True, reason="Written before we corrected how earnings reactions are measured")
    age = datetime.now(timezone.utc) - note.generated_at.replace(tzinfo=timezone.utc)
    if age > timedelta(days=STALENESS_DAYS):
        return StalenessRead(stale=True, reason=f"Generated over {STALENESS_DAYS} days ago")
    return StalenessRead(stale=False, reason=None)
