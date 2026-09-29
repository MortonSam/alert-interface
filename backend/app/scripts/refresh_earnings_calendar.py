"""Refresh the earnings calendar from Finnhub, every ticker, every run.

One Finnhub /calendar/earnings call for today..today+LOOKAHEAD_DAYS. For every
active ticker the stored future earnings dates are made equal to Finnhub's:
a date Finnhub lists is inserted or kept, a stored future date Finnhub no
longer lists is dropped (never kept as "confirmed"), and the ticker's
earnings_checked_at is set to now whether or not Finnhub had a date, so the
page can say "next earnings Oct 29 (Finnhub, checked today)". Past dates are
never touched: they are the record of reports that happened.

Usage
-----
    python -m app.scripts.refresh_earnings_calendar
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.finnhub_client import FinnhubClient
from app.services.step_outcomes import record_step_fields

LOOKAHEAD_DAYS = 120
STEP_LABEL = "Refresh earnings calendar (Finnhub)"


@dataclass
class Plan:
    """What one run did, per ticker, for the log and the step outcome."""
    checked: int = 0
    inserted: list[str] = field(default_factory=list)     # "SYM: 2026-10-29"
    replaced: list[str] = field(default_factory=list)     # "SYM: 2026-10-28 -> 2026-10-29"
    dropped: list[str] = field(default_factory=list)      # "SYM: dropped 2026-09-24 (yfinance); Finnhub lists nothing"
    unchanged: int = 0
    no_date: list[str] = field(default_factory=list)      # tickers Finnhub has no date for in the window

    def fields(self) -> dict:
        return {
            "checked": self.checked, "inserted": len(self.inserted), "replaced": len(self.replaced),
            "dropped": len(self.dropped), "unchanged": self.unchanged, "no_date": len(self.no_date),
            "dropped_examples": self.dropped[:10], "replaced_examples": self.replaced[:10],
        }


def _map_hour(raw: str | None) -> str:
    return raw if raw in ("bmo", "amc") else "unknown"


def finnhub_dates_by_symbol(entries: list[dict], today: date) -> dict[str, dict[date, str]]:
    """{symbol: {date: timing}} for calendar entries on or after today."""
    out: dict[str, dict[date, str]] = {}
    for e in entries:
        sym = e.get("symbol")
        try:
            d = date.fromisoformat(e["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not sym or d < today:
            continue
        out.setdefault(sym, {})[d] = _map_hour(e.get("hour"))
    return out


async def _upsert_timing(session, ticker_id, event_date: date, timing: str) -> None:
    if timing == "unknown":
        return
    stmt = (
        pg_insert(EarningsReportTiming)
        .values(ticker_id=ticker_id, event_date=event_date, timing=timing, source="finnhub")
        .on_conflict_do_update(index_elements=["ticker_id", "event_date"], set_={"timing": timing, "source": "finnhub"})
    )
    await session.execute(stmt)


async def reconcile(session, tickers: list[Ticker], entries: list[dict], now: datetime) -> Plan:
    """Make each ticker's stored future earnings dates equal to Finnhub's. Commits."""
    today = now.date()
    listed = finnhub_dates_by_symbol(entries, today)
    plan = Plan()

    for ticker in tickers:
        wanted = listed.get(ticker.symbol, {})
        stored = list((await session.execute(
            select(Event).where(
                Event.ticker_id == ticker.id,
                Event.event_type == EventType.EARNINGS,
                Event.event_date >= today,
            ).order_by(Event.event_date)
        )).scalars().all())
        stored_by_date = {e.event_date: e for e in stored}
        stored_next = stored[0].event_date if stored else None
        wanted_next = min(wanted) if wanted else None

        for d, timing in sorted(wanted.items()):
            existing = stored_by_date.get(d)
            if existing is not None:
                existing.source = DataSource.FINNHUB
                if existing.report_timing == "unknown" and timing != "unknown":
                    existing.report_timing = timing
                    existing.report_timing_source = "finnhub"
                plan.unchanged += 1
            else:
                session.add(Event(
                    ticker_id=ticker.id, event_type=EventType.EARNINGS, event_date=d,
                    title=f"{ticker.symbol} Earnings", source=DataSource.FINNHUB, is_confirmed=False,
                    metadata_={}, report_timing=timing,
                    report_timing_source="finnhub" if timing != "unknown" else "unknown",
                ))
                plan.inserted.append(f"{ticker.symbol}: {d.isoformat()}")
            await _upsert_timing(session, ticker.id, d, timing)

        for e in stored:
            if e.event_date not in wanted:
                src = getattr(e.source, "value", e.source)
                lists = f"Finnhub lists {wanted_next.isoformat()}" if wanted_next else "Finnhub lists nothing"
                plan.dropped.append(f"{ticker.symbol}: dropped {e.event_date.isoformat()} ({src}); {lists}")
                await session.delete(e)

        if stored_next and wanted_next and stored_next != wanted_next:
            plan.replaced.append(f"{ticker.symbol}: {stored_next.isoformat()} -> {wanted_next.isoformat()}")
        if not wanted:
            plan.no_date.append(ticker.symbol)

        ticker.earnings_checked_at = now
        plan.checked += 1

    await session.commit()
    return plan


async def main() -> int:
    now = datetime.now(timezone.utc)
    today = now.date()
    end = date.fromordinal(today.toordinal() + LOOKAHEAD_DAYS)

    finnhub = FinnhubClient()
    try:
        raw = await finnhub.get_earnings_calendar(today.isoformat(), end.isoformat())
    finally:
        await finnhub.close()
    entries = raw.get("earningsCalendar", [])
    print(f"Finnhub returned {len(entries)} earnings calendar entries for {today} .. {end}.")
    if not entries:
        # An empty calendar is a failed read, not "nobody reports for 120 days": change nothing.
        print("Finnhub returned no entries; stored dates left as they are and no ticker marked checked.")
        await record_step_fields(STEP_LABEL, {"checked": 0, "error": "Finnhub returned no calendar entries"})
        return 1

    async with ScriptSessionLocal() as session:
        tickers = list((await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
        )).scalars().all())
        plan = await reconcile(session, tickers, entries, now)

    print(f"\n{'─' * 50}")
    print(f"  Checked: {plan.checked}  Inserted: {len(plan.inserted)}  Replaced: {len(plan.replaced)}  "
          f"Dropped: {len(plan.dropped)}  Unchanged: {plan.unchanged}  No date in {LOOKAHEAD_DAYS}d: {len(plan.no_date)}")
    print(f"{'─' * 50}")
    for title, rows in (("Replaced", plan.replaced), ("Dropped", plan.dropped), ("Inserted", plan.inserted)):
        if rows:
            print(f"\n  {title} (first 10):")
            print("\n".join(f"    {r}" for r in rows[:10]))
    if plan.no_date:
        print(f"\n  No Finnhub date within {LOOKAHEAD_DAYS} days: {', '.join(plan.no_date[:20])}"
              + (" …" if len(plan.no_date) > 20 else ""))
    await record_step_fields(STEP_LABEL, plan.fields())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
