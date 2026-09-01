import asyncio
import os

import sentry_sdk
import sqlalchemy as sa
from fastapi import FastAPI, Request

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        environment=os.getenv("RAILWAY_ENVIRONMENT", "local"),
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from datetime import datetime, timezone

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers import admin, discover, events, historical_reactions, research_notes, system, tickers, watchlists, thesis
from app.services.system_metadata_service import get_value
from app.startup import lifespan, REFRESH_SENTINEL_MAX_MINUTES

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="Alert Interface API",
    description="Personal finance research tool: catalyst panel, watchlists, AI research.",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
        "refresh_in_progress": False,
        "last_refreshed_at": None,
        "rv_latest_date": None,
        "rv_last_run": None,
        "step_health": {},
        "step_outcomes": {},
    }

    try:
        async with AsyncSessionLocal() as session:
            # Real DB connectivity check — catches bad credentials / dead connections
            try:
                await asyncio.wait_for(
                    session.execute(sa.text("SELECT 1")),
                    timeout=2.0,
                )
            except (asyncio.TimeoutError, sa.exc.TimeoutError):
                result["status"] = "degraded"
                result["db"] = "slow"
                return JSONResponse(content=result, status_code=503)
            result["db"] = "ok"

            # Derive refresh_in_progress from the DB sentinel with staleness rule
            sentinel_raw = await get_value(session, "refresh_in_progress_since")
            if sentinel_raw and sentinel_raw != "done":
                try:
                    started_at = datetime.fromisoformat(sentinel_raw)
                    age_minutes = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
                    result["refresh_in_progress"] = age_minutes < REFRESH_SENTINEL_MAX_MINUTES
                except ValueError:
                    pass  # unparseable sentinel — treat as not in progress

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

            try:
                import json as _json
                raw = await get_value(session, "step_outcomes")
                result["step_outcomes"] = _json.loads(raw) if raw else {}
            except Exception:
                result["status"] = "degraded"
    except Exception:
        result["status"] = "error"
        result["db"] = "error"
        return JSONResponse(content=result, status_code=503)

    return result
