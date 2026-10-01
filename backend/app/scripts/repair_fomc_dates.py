"""Put every FOMC row on an official decision day.

The reactions seeder once carried its own list of decision days with four wrong ones (2025-12-17 for Dec 10,
2026-09-17 for Sep 16, 2026-10-29 for Oct 28, 2026-12-16 for Dec 9), and the macro scraper wrote the official
day beside it, so one meeting had two "FOMC Meeting" events and reaction rows measured the wrong sessions.
services/fomc_calendar.py is now the only source. This script:

  1. deletes every fomc reaction row whose date is not an official decision day,
  2. deletes every "FOMC Meeting" event whose date is not an official decision day,
  3. inserts the official events that are missing,
  4. seeds, for each official day in the seeder's window that has no reaction rows, every active ticker
     not on the price-history exclusion list (2025-12-10 today).

Dry run by default: it prints, per date, the event rows and reaction rows it would delete and the tickers
it would seed, and writes nothing. --write applies it.

Usage
-----
    python -m app.scripts.repair_fomc_dates            # dry run
    python -m app.scripts.repair_fomc_dates --write
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app.constants import LISTING_DATE_OVERRIDES
from app.database import ScriptSessionLocal
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.seed_fomc_reactions import LOOKBACK_YEARS, MIN_AGE_DAYS, _process_ticker_bulk
from app.services.fomc_calendar import FOMC_EVENT_TITLE, decision_days, ensure_fomc_events, is_decision_day
from app.services.price_history_exclusion import exclusion_list


@dataclass
class Plan:
    delete_reactions: dict[date, int] = field(default_factory=dict)     # wrong date -> rows
    delete_events: dict[date, int] = field(default_factory=dict)        # wrong date -> rows
    insert_events: list[date] = field(default_factory=list)             # official days with no event row
    seed: dict[date, list[str]] = field(default_factory=dict)           # official day in the window -> tickers to seed

    def empty(self) -> bool:
        return not (self.delete_reactions or self.delete_events or self.insert_events or self.seed)


def plan(reaction_days: dict[date, int], event_days: dict[date, int], symbols_with_rows: dict[date, set[str]],
         candidates: list[str], today: date) -> Plan:
    """Pure: what to delete, insert and seed, from what is stored. `candidates` are active, non-excluded symbols."""
    p = Plan()
    p.delete_reactions = {d: n for d, n in sorted(reaction_days.items()) if not is_decision_day(d)}
    p.delete_events = {d: n for d, n in sorted(event_days.items()) if not is_decision_day(d)}
    p.insert_events = [d for d in decision_days() if d not in event_days]
    lookback = today - timedelta(days=LOOKBACK_YEARS * 366)
    cutoff = today - timedelta(days=MIN_AGE_DAYS)
    for d in decision_days(lookback, cutoff):
        have = symbols_with_rows.get(d, set())
        need = [s for s in candidates if s not in have and (LISTING_DATE_OVERRIDES.get(s) is None or d >= LISTING_DATE_OVERRIDES[s])]
        if need and len(have) < len(candidates) // 2:      # a day the seeder never ran, not a few stragglers
            p.seed[d] = need
    return p


async def _stored(session) -> tuple[dict[date, int], dict[date, int], dict[date, set[str]], list[str]]:
    reaction_days = dict((await session.execute(
        select(HistoricalReaction.event_date, func.count()).where(HistoricalReaction.event_type == EventType.FOMC).group_by(HistoricalReaction.event_date)
    )).all())
    event_days = dict((await session.execute(
        select(Event.event_date, func.count()).where(Event.ticker_id.is_(None), Event.title == FOMC_EVENT_TITLE).group_by(Event.event_date)
    )).all())
    rows = (await session.execute(
        select(HistoricalReaction.event_date, Ticker.symbol).join(Ticker, Ticker.id == HistoricalReaction.ticker_id)
        .where(HistoricalReaction.event_type == EventType.FOMC)
    )).all()
    with_rows: dict[date, set[str]] = {}
    for d, sym in rows:
        with_rows.setdefault(d, set()).add(sym)
    active = list((await session.execute(select(Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    excluded = await exclusion_list(session, "FOMC reactions")
    return reaction_days, event_days, with_rows, [s for s in active if s not in excluded]


def print_plan(p: Plan, write: bool) -> None:
    mode = "APPLYING" if write else "DRY RUN (nothing written)"
    print(f"\n{'─' * 60}\n  repair_fomc_dates: {mode}\n{'─' * 60}")
    if p.empty():
        print("  Every FOMC row is on an official decision day; nothing to do.")
        return
    for d in sorted(set(p.delete_reactions) | set(p.delete_events)):
        print(f"  {d.isoformat()}  not an official decision day: delete {p.delete_reactions.get(d, 0)} reaction row(s), "
              f"{p.delete_events.get(d, 0)} event row(s)")
    for d in p.insert_events:
        print(f"  {d.isoformat()}  official day with no event row: insert the event")
    for d, syms in p.seed.items():
        print(f"  {d.isoformat()}  official day with no reactions: seed {len(syms)} ticker(s)")
        print("      " + ", ".join(syms))


async def apply(p: Plan) -> None:
    async with ScriptSessionLocal() as session:
        for d in p.delete_reactions:
            await session.execute(delete(HistoricalReaction).where(HistoricalReaction.event_type == EventType.FOMC, HistoricalReaction.event_date == d))
        for d in p.delete_events:
            await session.execute(delete(Event).where(Event.ticker_id.is_(None), Event.title == FOMC_EVENT_TITLE, Event.event_date == d))
        inserted = await ensure_fomc_events(session)
        await session.commit()
        print(f"  deleted reactions on {len(p.delete_reactions)} date(s), events on {len(p.delete_events)} date(s); inserted {inserted} event(s)")
        event_ids = {d: str(i) for d, i in (await session.execute(
            select(Event.event_date, Event.id).where(Event.ticker_id.is_(None), Event.title == FOMC_EVENT_TITLE)
        )).all()}
        tickers = {t.symbol: t for t in (await session.execute(select(Ticker))).scalars().all()}
    loop = asyncio.get_event_loop()
    for d, syms in p.seed.items():
        ok = failed = 0
        for sym in syms:
            good, *_rest, reason = await _process_ticker_bulk(tickers[sym], [(d, event_ids[d])], loop, LISTING_DATE_OVERRIDES.get(sym))
            if good:
                ok += 1
            else:
                failed += 1
                print(f"    {sym}: {reason}")
        print(f"  {d.isoformat()}: seeded {ok} ticker(s), {failed} failed")


async def main(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as session:
        reaction_days, event_days, with_rows, candidates = await _stored(session)
    p = plan(reaction_days, event_days, with_rows, candidates, date.today())
    print_plan(p, write)
    if write and not p.empty():
        await apply(p)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
