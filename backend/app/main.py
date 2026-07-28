import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers import admin, discover, events, historical_reactions, research_notes, system, tickers, watchlists, thesis
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
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
@app.get("/api/v1/health", tags=["meta"])
async def health_check():
    """Rich health probe — safe on empty DB, no auth required.

    Performs a real ``SELECT 1`` to catch credential / connection breaks.
    Returns non-200 when the DB is unreachable so Railway's healthcheck
    flags the deploy instead of showing green.
    """
    result: dict = {
        "status": "ok",
        "db": "ok",
        "refresh_in_progress": _startup._refresh_in_progress,
        "last_refreshed_at": None,
        "rv_latest_date": None,
        "rv_last_run": None,
        "step_health": {},
    }

    try:
        async with AsyncSessionLocal() as session:
            # Real DB connectivity check — catches bad credentials / dead connections
            await session.execute(sa.text("SELECT 1"))
            result["db"] = "ok"

            result["last_refreshed_at"] = await get_value(session, "last_refreshed_at")

            try:
                rv_row = await session.execute(
                    sa.text("SELECT max(as_of_date) FROM rv_snapshots WHERE status = 'ok'")
                )
                rv_date = rv_row.scalar()
                result["rv_latest_date"] = rv_date.isoformat() if rv_date else None
            except Exception:
                result["status"] = "degraded"

            try:
                result["rv_last_run"] = await get_value(session, "rv_last_run")
            except Exception:
                result["status"] = "degraded"

            try:
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
    except Exception:
        result["status"] = "error"
        result["db"] = "error"
        return JSONResponse(content=result, status_code=503)

    return result
