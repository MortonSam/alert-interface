"""Record a report date the company itself has announced, when no calendar source or feed has carried it yet, and retire the
estimates it replaces. Dry run by default: prints the plan. --write stores the confirmed event (source edgar, the value the
calendar uses for company announcements; note "confirmed: company announcement <url>"; report timing and its source) and
deletes every unconfirmed future estimate up to SAME_REPORT_DAYS before it (the same quarterly report under an earlier date; a later
estimate may be the next quarter and is left alone).

    python -m app.scripts.record_report_date FDX 2026-10-28 amc https://investors.fedex.com/...        # dry run
    python -m app.scripts.record_report_date FDX 2026-10-28 amc https://investors.fedex.com/... --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.earnings_calendar import SAME_REPORT_DAYS

TIMINGS = ("amc", "bmo", "unknown")


def note_for(url: str) -> str:
    return f"confirmed: company announcement {url}"


def plan_changes(stored: list[Event], day: date, today: date) -> tuple[Event | None, list[Event]]:
    """Pure: (the stored event on `day`, if any; the unconfirmed future estimates within SAME_REPORT_DAYS of it to delete)."""
    same = next((e for e in stored if e.event_date == day), None)
    # only an earlier estimate is the same report under another date: a later one within the window may be the next quarter (FDX: Oct 28 then Dec 16)
    drop = [e for e in stored if not e.is_confirmed and today <= e.event_date < day and (day - e.event_date).days < SAME_REPORT_DAYS]
    return same, drop


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 4 or args[2] not in TIMINGS or not args[3].startswith("http"):
        print(__doc__); return 2
    sym, day, timing, url = args[0].upper(), date.fromisoformat(args[1]), args[2], args[3]
    today = date.today()
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        ticker = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
        if ticker is None:
            print(f"no ticker {sym}"); return 2
        stored = list((await s.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date >= today.replace(day=1)).order_by(Event.event_date))).scalars().all())
        same, drop = plan_changes(stored, day, today)
        print(f"{sym}: stored earnings dates from this month: " + (", ".join(f"{e.event_date} ({'confirmed' if e.is_confirmed else 'estimate'}, {getattr(e.source, 'value', e.source)})" for e in stored) or "none"))
        print(f"  {'update' if same else 'insert'} {day} {timing}: confirmed, {note_for(url)}")
        for e in drop:
            print(f"  delete {e.event_date} ({getattr(e.source, 'value', e.source)}; {e.confirmation_note}): the same report under another date")
        if not write:
            print("  dry run, nothing written"); return 0
        if same is None:
            s.add(Event(ticker_id=ticker.id, event_type=EventType.EARNINGS, event_date=day, title=f"{sym} Earnings", source=DataSource.EDGAR, is_confirmed=True,
                        confirmation_note=note_for(url), checked_at=now, metadata_={}, report_timing=timing, report_timing_source="company" if timing != "unknown" else "unknown"))
        else:
            same.source, same.is_confirmed, same.confirmation_note, same.checked_at, same.unresolved_since, same.sources_checked = DataSource.EDGAR, True, note_for(url), now, None, None
            if timing != "unknown":
                same.report_timing, same.report_timing_source = timing, "company"
        for e in drop:
            await s.delete(e)
        if timing != "unknown":
            from app.scripts.refresh_earnings_calendar import _upsert_timing
            await _upsert_timing(s, ticker.id, day, timing, "company")
        await s.commit()
        print("  recorded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
