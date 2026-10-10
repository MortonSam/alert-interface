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

import logging
_log = logging.getLogger("headline_guard")
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
    up_items, down_items, ranked, change, suppressed, session = await build_sections(db, now)
    for x in suppressed.values():          # every suppression, with both numbers, in the logs
        _log.info("headline suppressed: %s %r (%s; stated %s, ours %s)", x["symbol"], x["headline"], x["reason"], x["stated_pct"], x["move_pct"])
    return NewsSectionsResponse(
        visible=True, quotes_as_of=max((q["quote_time"] for q in session), default=None),
        up=up_items, down=down_items,
        stories=[NewsStoryItem(symbol=r["symbol"], change_pct=change[r["symbol"]], headline=r["headline"], url=r["url"], source=r["source"],
                               published_at=r["published_at"]) for r in ranked],
    )



async def build_sections(db, now: datetime):
    """The movers (with headlines), "In the news" and the suppressed headlines from the stored quotes and stories, as of `now`.
    Shared by the route and validate's news_headline_guard check."""
    from app.services import news as N
    qrows = (await db.execute(sa.text("""
        SELECT q.symbol, t.name, q.price, q.change_pct, q.quote_time FROM quote_snapshots q
        JOIN tickers t ON t.symbol = q.symbol AND t.is_active"""))).all()
    quotes = [{"symbol": r.symbol, "name": r.name, "price": float(r.price) if r.price is not None else None,
               "change_pct": float(r.change_pct) if r.change_pct is not None else None, "quote_time": r.quote_time} for r in qrows]
    session = N.session_quotes(quotes)
    up, down = N.movers(quotes)
    # the news window follows the session the prices come from: from the close before that session until now (not a rolling 24
    # hours), so Friday's movers keep their headlines over the weekend and before Monday's open
    session_day = max((q["quote_time"] for q in session), default=now).astimezone(N.NEW_YORK).date()
    since = N.previous_session_close(session_day)
    srows = (await db.execute(sa.text("""
        SELECT url, headline, source, published_at, related FROM news_stories
        WHERE published_at >= :c AND published_at <= :n AND cardinality(related) > 0"""), {"c": since, "n": now})).all()
    stories = [{"url": r.url, "headline": r.headline, "source": r.source, "published_at": r.published_at, "related": list(r.related)} for r in srows]
    last_reports = dict((await db.execute(sa.text("""
        SELECT t.symbol, max(d) FROM tickers t JOIN (
            SELECT ticker_id, event_date AS d FROM historical_reactions WHERE event_type = 'earnings' AND event_date <= :today
            UNION ALL
            SELECT ticker_id, event_date FROM events WHERE event_type = 'earnings' AND is_confirmed AND event_date <= :today
        ) x ON x.ticker_id = t.id WHERE t.is_active GROUP BY t.symbol"""), {"today": session_day})).all())

    change = {q["symbol"]: q["change_pct"] for q in session}
    # the guard compares a headline's stated percent with the exact figure the page prints beside it: the quote's change
    moves = change
    suppressed: dict = {}

    names = {q["symbol"]: q["name"] for q in quotes}

    def mover(q: dict) -> MoverItem:
        h = N.top_headline(stories, q["symbol"], q["name"], last_reports.get(q["symbol"]), since, moves.get(q["symbol"]), suppressed, names)
        return MoverItem(symbol=q["symbol"], name=q["name"], price=q["price"], change_pct=q["change_pct"], quote_time=q["quote_time"],
                         headline=NewsHeadline(headline=h["headline"], url=h["url"], source=h["source"], published_at=h["published_at"]) if h else None)

    up_items, down_items = [mover(q) for q in up], [mover(q) for q in down]
    ranked = N.in_the_news(stories, change, names=names, last_reports=last_reports, since=since, moves=moves, suppressed=suppressed,
                           exclude_urls={m.headline.url for m in up_items + down_items if m.headline})
    return up_items, down_items, ranked, change, suppressed, session
