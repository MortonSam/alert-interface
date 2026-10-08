"""Discover's news sections (services/news), behind DISCOVER_NEWS_ENABLED; the admin token sees them while the flag is off. Kept out
of routers/discover.py, whose ledger gates must read may_read_ledger and never is_admin (test_reviewer_key)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.database import get_db

router = APIRouter(prefix="/discover", tags=["discover"])


# ── News (behind DISCOVER_NEWS_ENABLED; the admin token sees it while the flag is off) ─────────────────────────────────────────────


class NewsHeadline(BaseModel):
    headline: str
    url: str
    source: str | None = None
    published_at: datetime


class MoverItem(BaseModel):
    symbol: str
    name: str | None = None
    price: float
    change_pct: float
    quote_time: datetime              # the last trade's time, from the stored quote
    headline: NewsHeadline | None = None


class NewsStoryItem(NewsHeadline):
    symbol: str
    change_pct: float


class NewsSectionsResponse(BaseModel):
    visible: bool
    reason: str | None = None
    quotes_as_of: datetime | None = None
    up: list[MoverItem] = []
    down: list[MoverItem] = []
    stories: list[NewsStoryItem] = []


@router.get("/news", response_model=NewsSectionsResponse)
async def discover_news(db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> NewsSectionsResponse:
    """"Today's biggest movers" and "In the news" from stored headlines and the stored quote snapshot (services/news). Fails closed."""
    import json as _json
    from app.config import settings
    from app.services import news as N
    from app.services.system_metadata_service import get_value
    if not (settings.discover_news_enabled or admin):
        return NewsSectionsResponse(visible=False, reason="off")
    now = datetime.now(timezone.utc)
    newest_story = (await db.execute(sa.text("SELECT max(published_at) FROM news_stories"))).scalar()
    newest_quote = (await db.execute(sa.text("SELECT max(captured_at) FROM quote_snapshots"))).scalar()
    outcomes = _json.loads(await get_value(db, "step_outcomes") or "{}")
    step_exit = (outcomes.get(N.STEP_LABEL) or {}).get("exit")
    vis = N.visibility(newest_story, step_exit, now, newest_quote)
    if not vis.visible:
        return NewsSectionsResponse(visible=False, reason=vis.reason)
    qrows = (await db.execute(sa.text("""
        SELECT q.symbol, t.name, q.price, q.change_pct, q.quote_time FROM quote_snapshots q
        JOIN tickers t ON t.symbol = q.symbol AND t.is_active"""))).all()
    quotes = [{"symbol": r.symbol, "name": r.name, "price": float(r.price) if r.price is not None else None,
               "change_pct": float(r.change_pct) if r.change_pct is not None else None, "quote_time": r.quote_time} for r in qrows]
    session = N.session_quotes(quotes)
    srows = (await db.execute(sa.text("""
        SELECT url, headline, source, published_at, related FROM news_stories
        WHERE published_at >= :c AND cardinality(related) > 0"""), {"c": now - timedelta(hours=N.FRESH_HOURS)})).all()
    stories = [{"url": r.url, "headline": r.headline, "source": r.source, "published_at": r.published_at, "related": list(r.related)} for r in srows]
    up, down = N.movers(quotes)

    def mover(q: dict) -> MoverItem:
        h = N.top_headline(stories, q["symbol"], q["name"])
        return MoverItem(symbol=q["symbol"], name=q["name"], price=q["price"], change_pct=q["change_pct"], quote_time=q["quote_time"],
                         headline=NewsHeadline(headline=h["headline"], url=h["url"], source=h["source"], published_at=h["published_at"]) if h else None)

    change = {q["symbol"]: q["change_pct"] for q in session}
    ranked = N.in_the_news(stories, change, names={q["symbol"]: q["name"] for q in quotes})
    return NewsSectionsResponse(
        visible=True, quotes_as_of=max((q["quote_time"] for q in session), default=None),
        up=[mover(q) for q in up], down=[mover(q) for q in down],
        stories=[NewsStoryItem(symbol=r["symbol"], change_pct=change[r["symbol"]], headline=r["headline"], url=r["url"], source=r["source"],
                               published_at=r["published_at"]) for r in ranked],
    )

