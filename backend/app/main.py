from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import events, historical_reactions, tickers, watchlists

app = FastAPI(
    title="Alert Interface API",
    description="Personal finance research tool — catalyst panel, watchlists, AI research.",
    version="0.1.0",
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickers.router, prefix="/api/v1")
app.include_router(watchlists.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(historical_reactions.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
