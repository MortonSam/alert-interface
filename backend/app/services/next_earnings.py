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
from app.services.earnings_calendar import company_confirmed, level_of
from app.services.personal_use import dates_licensed_only

UNRESOLVED_SHOWN_DAYS = 45   # an unresolved estimate older than this is no longer "expected around"
EXPECTED_WINDOW = "expected_window"   # the confirmation level of a name with no company-confirmed date and a window from its filings
# Sam's approved words for that level (2026-10-26), verbatim; frontend lib/earningsSource.expectedWindowLine is the same template (tested)
EXPECTED_WINDOW_LINE = "Next report expected around {date}, based on its past report dates (not yet confirmed by the company)"


# a day from the company's own events calendar (Sam, 2026-10-27: NVIDIA's "11/16/2026 - 11/17/2026" results listing) takes the
# window's place; its line names that source instead of past report dates (frontend lib/earningsSource.expectedWindowLine, tested)
CALENDAR_SOURCE = "the company's own events calendar"
# Sam's words (2026-10-27), verbatim
CALENDAR_LINE = "Next report expected around {date}, per {company}'s events calendar (exact date and time not yet announced)"


def expected_window_line(center: date, source: str | None = None, company: str | None = None) -> str:
    day = center.strftime("%b %-d, %Y")
    if source == CALENDAR_SOURCE and company:
        return CALENDAR_LINE.format(date=day, company=company)
    return EXPECTED_WINDOW_LINE.format(date=day)


@dataclass
class NextEarnings:
    date: date | None = None
    source: str | None = None
    confirmation: str | None = None    # "confirmed" | "estimated" | "expected_unconfirmed" | "expected_window" | None
    note: str | None = None
    checked_at: datetime | None = None
    window_start: date | None = None   # with LICENSED_DATES_ONLY and no company-confirmed date: the expected window (services/report_windows)
    window_end: date | None = None
    window_center: date | None = None  # the projected report day the window is built around: "expected around" names it
    window_source: str | None = None
    window_company: str | None = None    # with CALENDAR_SOURCE: the company's short name the line names
    window_computed_at: str | None = None

    def as_api(self, prefix: str = "next_earnings_") -> dict:
        d = asdict(self)
        return {prefix + k: v for k, v in d.items()}


def choose(events: list[Event], today: date, licensed_only: bool = False) -> tuple[date | None, str | None, str | None, str | None]:
    """(date, source, confirmation, note) from a ticker's earnings events, by precedence. With `licensed_only` (LICENSED_DATES_ONLY)
    only a company-confirmed date is a date at all: a vendor's estimate, or two vendors agreeing, is never shown."""
    future = sorted((e for e in events if e.event_date >= today), key=lambda e: e.event_date)
    if licensed_only:
        confirmed = [e for e in future if company_confirmed(e.is_confirmed, e.confirmation_note)]
        if not confirmed:
            return None, None, None, None
        pick = confirmed[0]
        return pick.event_date, getattr(pick.source, "value", pick.source), "confirmed", pick.confirmation_note
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


async def batch_next_earnings(session: AsyncSession, ticker_ids: list, today: date | None = None) -> dict:
    """{ticker_id: NextEarnings} for the given tickers, judged as of `today` (the real date unless a caller fixes one)."""
    if not ticker_ids:
        return {}
    today = today or date.today()
    from app.config import settings
    licensed_only = dates_licensed_only()
    tickers = (await session.execute(select(Ticker.id, Ticker.symbol, Ticker.name, Ticker.earnings_checked_at).where(Ticker.id.in_(ticker_ids)))).all()
    out = {t.id: NextEarnings(checked_at=t.earnings_checked_at) for t in tickers}
    symbol_of = {t.id: t.symbol for t in tickers}
    name_of = {t.id: t.name for t in tickers}
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
        d, src, level, note = choose(events, today, licensed_only)
        ne = out.setdefault(tid, NextEarnings())
        ne.date, ne.source, ne.confirmation, ne.note = d, src, level, note
    if licensed_only:
        await attach_windows(session, out, symbol_of, today, name_of)
    return out


async def attach_windows(session: AsyncSession, out: dict, symbol_of: dict, today: date, name_of: dict | None = None) -> None:
    """A name with no company-confirmed date shows its expected window from SEC filing dates, when one is stored and still ahead; a
    day its own events calendar lists (scripts/confirm_report_dates.CALENDAR_KEY) takes the window's place."""
    import json as _json
    from sqlalchemy import text as _text
    from app.scripts.confirm_report_dates import CALENDAR_KEY
    from app.services.report_windows import KEY, window_from_record
    need = {tid: symbol_of[tid] for tid, ne in out.items() if ne.date is None and tid in symbol_of}
    if not need:
        return
    keys = [KEY.format(sym=s) for s in need.values()] + [CALENDAR_KEY.format(sym=s) for s in need.values()]
    rows = (await session.execute(_text("SELECT key, value FROM system_metadata WHERE key = ANY(:k)"), {"k": keys})).all()
    by_key = {k: v for k, v in rows}
    for tid, sym in need.items():
        try:
            cal = _json.loads(by_key.get(CALENDAR_KEY.format(sym=sym)) or "null")
        except ValueError:
            cal = None
        if cal and date.fromisoformat(cal["day"]) >= today:
            ne = out[tid]
            ne.confirmation, ne.window_center = EXPECTED_WINDOW, date.fromisoformat(cal["day"])
            ne.window_start, ne.window_end = date.fromisoformat(cal["start"]), date.fromisoformat(cal["end"])
            ne.window_source, ne.window_computed_at = CALENDAR_SOURCE, cal.get("seen_on")
            from app.services.briefing import short_name
            ne.window_company = short_name((name_of or {}).get(tid), sym) or sym
            continue
        w = window_from_record(by_key.get(KEY.format(sym=sym)))
        if not w or date.fromisoformat(w["end"]) < today:
            continue
        ne = out[tid]
        ne.confirmation, ne.window_start, ne.window_end = EXPECTED_WINDOW, date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        ne.window_center = date.fromisoformat(w["center"]) if w.get("center") else None
        ne.window_source, ne.window_computed_at = w.get("source"), w.get("computed_at")


async def next_earnings_for(session: AsyncSession, ticker_id, today: date | None = None) -> NextEarnings:
    return (await batch_next_earnings(session, [ticker_id], today)).get(ticker_id, NextEarnings())
