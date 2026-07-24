import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers import discover, events, historical_reactions, research_notes, system, tickers, watchlists, thesis
from app.services.system_metadata_service import get_value
from app.startup import lifespan
import app.startup as _startup

app = FastAPI(
    title="Alert Interface API",
    description="Personal finance research tool — catalyst panel, watchlists, AI research.",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(discover.router, prefix="/api/v1")
app.include_router(tickers.router, prefix="/api/v1")
app.include_router(watchlists.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(historical_reactions.router, prefix="/api/v1")
app.include_router(research_notes.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(thesis.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
@app.get("/api/v1/health", tags=["meta"])
async def health_check() -> dict:
    """Rich health probe — safe on empty DB, no auth required."""
    result: dict = {"status": "ok", "refresh_in_progress": _startup._refresh_in_progress}

    try:
        async with AsyncSessionLocal() as session:
            last = await get_value(session, "last_refreshed_at")
            result["last_refreshed_at"] = last

            # Latest RV snapshot date
            rv_row = await session.execute(
                sa.text("SELECT max(as_of_date) FROM rv_snapshots WHERE status = 'ok'")
            )
            rv_date = rv_row.scalar()
            result["rv_latest_date"] = rv_date.isoformat() if rv_date else None

            # RV last-run summary
            rv_summary = await get_value(session, "rv_last_run")
            result["rv_last_run"] = rv_summary

            # Per-step health timestamps
            step_rows = await session.execute(
                sa.text("SELECT key, value FROM system_metadata WHERE key LIKE 'step:%'")
            )
            steps = {}
            for row in step_rows:
                label = row[0].replace("step:", "").replace(":last_success", "")
                steps[label] = row[1]
            result["step_health"] = steps
    except Exception:
        result["status"] = "degraded"

    return result
