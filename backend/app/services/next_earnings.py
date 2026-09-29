"""One answer to "when does this company report next", for every page that prints it.

Precedence: a confirmed future date; else the nearest future estimate; else an estimate that
passed unresolved ("expected around <date>; not confirmed"); else nothing, with the time the
calendar was last asked. Every field comes from the events row and the ticker, never the request.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.earnings_calendar import level_of

UNRESOLVED_SHOWN_DAYS = 45   # an unresolved estimate older than this is no longer "expected around"


@dataclass
class NextEarnings:
    date: date | None = None
    source: str | None = None
    confirmation: str | None = None    # "confirmed" | "estimated" | "expected_unconfirmed" | None
    note: str | None = None
    checked_at: datetime | None = None

    def as_api(self, prefix: str = "next_earnings_") -> dict:
        d = asdict(self)
        return {prefix + k: v for k, v in d.items()}


def choose(events: list[Event], today: date) -> tuple[date | None, str | None, str | None, str | None]:
    """(date, source, confirmation, note) from a ticker's earnings events, by precedence."""
    future = sorted((e for e in events if e.event_date >= today), key=lambda e: e.event_date)
    confirmed = [e for e in future if e.is_confirmed]
    pick = confirmed[0] if confirmed else (future[0] if future else None)
    if pick is None:
        unresolved = [e for e in events if e.unresolved_since is not None and (today - e.event_date).days <= UNRESOLVED_SHOWN_DAYS]
        if unresolved:
            pick = max(unresolved, key=lambda e: e.event_date)
    if pick is None:
        return None, None, None, None
    src = getattr(pick.source, "value", pick.source)
    return pick.event_date, src, level_of(pick.is_confirmed, pick.unresolved_since), pick.confirmation_note


async def batch_next_earnings(session: AsyncSession, ticker_ids: list) -> dict:
    """{ticker_id: NextEarnings} for the given tickers."""
    if not ticker_ids:
        return {}
    today = date.today()
    tickers = (await session.execute(select(Ticker.id, Ticker.earnings_checked_at).where(Ticker.id.in_(ticker_ids)))).all()
    out = {t.id: NextEarnings(checked_at=t.earnings_checked_at) for t in tickers}
    rows = (await session.execute(
        select(Event).where(
            Event.ticker_id.in_(ticker_ids), Event.event_type == EventType.EARNINGS,
            Event.event_date >= today - timedelta(days=UNRESOLVED_SHOWN_DAYS),
        )
    )).scalars().all()
    by_ticker: dict = {}
    for e in rows:
        by_ticker.setdefault(e.ticker_id, []).append(e)
    for tid, events in by_ticker.items():
        d, src, level, note = choose(events, today)
        ne = out.setdefault(tid, NextEarnings())
        ne.date, ne.source, ne.confirmation, ne.note = d, src, level, note
    return out


async def next_earnings_for(session: AsyncSession, ticker_id) -> NextEarnings:
    return (await batch_next_earnings(session, [ticker_id])).get(ticker_id, NextEarnings())
