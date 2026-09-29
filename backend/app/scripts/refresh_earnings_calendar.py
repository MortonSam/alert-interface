"""Refresh the earnings calendar: every source, every active ticker, every run, with a confirmation level.

Sources, per run:
  Finnhub   one /calendar/earnings call, today-60 .. today+LOOKAHEAD_DAYS: future estimates and, in the
            past part, which reports carried an actual EPS.
  Yahoo     per-ticker earnings_dates (future estimates with their time of day; reported EPS for the past),
            in a thread pool inside YFINANCE_BUDGET_SECONDS; tickers not reached keep Finnhub only.
  Company   Finnhub company news and EDGAR 8-K Items 7.01/8.01 (report_announcements) for tickers whose
            nearest candidate is within ANNOUNCE_WINDOW_DAYS: the one source that confirms a date.
  EDGAR     8-K Item 2.02 for an estimate that passed in the last few days with no report found.

Decisions are earnings_calendar.merge_future / resolve_past / beyond_calendar_reach (pure, tested); this
script fetches and applies. A stored date beyond a calendar source's reach (a reaction row, an actual EPS,
an EDGAR source, a company announcement) is kept as it is whatever Finnhub or Yahoo list, and a calendar
date within NEAR_DAYS of it is the same report and is not inserted beside it. Every active ticker's
earnings_checked_at is set whether or not a date came back.

Usage
-----
    python -m app.scripts.refresh_earnings_calendar
"""
from __future__ import annotations

import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.earnings_calendar import (
    EDGAR_202_LOOKBACK_DAYS, NEAR_DAYS, Candidate, FutureDate, PastResolution, StoredDate, beyond_calendar_reach,
    merge_future, resolve_past,
)
from app.services.edgar_client import EdgarClient
from app.services.finnhub_client import FinnhubClient
from app.services.report_announcements import edgar_ir_8ks, from_8k_text, from_news
from app.services.step_outcomes import record_step_fields

LOOKAHEAD_DAYS = 120
PAST_LOOKBACK_DAYS = 60          # past estimated events this old are re-resolved
YFINANCE_BUDGET_SECONDS = 300
YFINANCE_WORKERS = 6
ANNOUNCE_WINDOW_DAYS = 60        # look for a company announcement when the nearest candidate is this close
ANNOUNCE_BUDGET_SECONDS = 240
STEP_LABEL = "Refresh earnings calendar (Finnhub)"
SOURCE_ENUM = {"finnhub": DataSource.FINNHUB, "yfinance": DataSource.YFINANCE, "company": DataSource.EDGAR}


@dataclass
class Plan:
    checked: int = 0
    inserted: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)        # beyond a calendar source's reach, whatever the sources list
    confirmed: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    reported: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    unchanged: int = 0
    no_date: list[str] = field(default_factory=list)
    yfinance_reached: int = 0
    announcements_checked: int = 0

    def fields(self) -> dict:
        return {
            "checked": self.checked, "inserted": len(self.inserted), "replaced": len(self.replaced),
            "dropped": len(self.dropped), "kept": len(self.kept), "confirmed": len(self.confirmed), "unresolved": len(self.unresolved),
            "reported": len(self.reported), "superseded": len(self.superseded), "unchanged": self.unchanged,
            "no_date": len(self.no_date), "yfinance_reached": self.yfinance_reached,
            "announcements_checked": self.announcements_checked,
            "unresolved_list": self.unresolved[:50], "confirmed_examples": self.confirmed[:10],
            "replaced_examples": self.replaced[:10], "dropped_examples": self.dropped[:10], "kept_examples": self.kept[:10],
        }


def _map_hour(raw: str | None) -> str:
    return raw if raw in ("bmo", "amc") else "unknown"


# ── Sources ──────────────────────────────────────────────────────────────────

def finnhub_by_symbol(entries: list[dict], today: date) -> tuple[dict[str, dict[date, str]], dict[str, list[date]]]:
    """({symbol: {future date: timing}}, {symbol: [dates with an actual EPS]}).

    An entry with an actual EPS is a report that happened, whatever its date (today's included): it is
    evidence, never a future estimate."""
    future: dict[str, dict[date, str]] = {}
    actual: dict[str, list[date]] = {}
    for e in entries:
        sym = e.get("symbol")
        try:
            d = date.fromisoformat(e["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not sym:
            continue
        if e.get("epsActual") is not None:
            actual.setdefault(sym, []).append(d)
        elif d >= today:
            future.setdefault(sym, {})[d] = _map_hour(e.get("hour"))
    return future, actual


def _yf_fetch(symbol: str) -> tuple[dict[date, str], list[date]]:
    """Sync: ({future date: timing}, [past dates with a reported EPS]) from Yahoo's earnings_dates."""
    import math
    import yfinance as yf
    df = yf.Ticker(symbol).get_earnings_dates(limit=12)
    future: dict[date, str] = {}
    reported: list[date] = []
    if df is None or df.empty:
        return future, reported
    today = date.today()
    for ts, row in df.iterrows():
        try:
            d = ts.date()
        except Exception:
            continue
        if d >= today:
            hour = getattr(ts, "hour", None)
            timing = "amc" if hour is not None and hour >= 15 else "bmo" if hour is not None and hour < 10 else "unknown"
            future[d] = timing
        else:
            val = row.get("Reported EPS")
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                reported.append(d)
    return future, reported


async def yfinance_by_symbol(symbols: list[str], budget_s: float) -> tuple[dict[str, dict[date, str]], dict[str, list[date]], set[str]]:
    """Per-ticker Yahoo fetch inside a budget. Returns (future, reported, reached)."""
    loop = asyncio.get_event_loop()
    future: dict[str, dict[date, str]] = {}
    reported: dict[str, list[date]] = {}
    reached: set[str] = set()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=YFINANCE_WORKERS) as pool:
        for i in range(0, len(symbols), YFINANCE_WORKERS):
            if time.monotonic() - started > budget_s:
                print(f"  yfinance: budget of {budget_s:.0f}s reached after {len(reached)} tickers", flush=True)
                break
            batch = symbols[i:i + YFINANCE_WORKERS]
            results = await asyncio.gather(*[loop.run_in_executor(pool, _yf_fetch, s) for s in batch], return_exceptions=True)
            for sym, res in zip(batch, results):
                if isinstance(res, Exception):
                    continue
                future[sym], reported[sym] = res
                reached.add(sym)
    return future, reported, reached


# ── Apply ────────────────────────────────────────────────────────────────────

async def _upsert_timing(session, ticker_id, event_date: date, timing: str, source: str) -> None:
    if timing == "unknown":
        return
    stmt = (
        pg_insert(EarningsReportTiming)
        .values(ticker_id=ticker_id, event_date=event_date, timing=timing, source=source)
        .on_conflict_do_update(index_elements=["ticker_id", "event_date"], set_={"timing": timing, "source": source})
    )
    await session.execute(stmt)


async def apply_ticker(session, ticker: Ticker, stored: list[Event], protected: dict[date, str],
                       decided: list[FutureDate], past: list[tuple[Event, PastResolution]], now: datetime, plan: Plan) -> None:
    """Write one ticker's decided future dates and past resolutions.

    `stored` is the ticker's stored dates on or after today; `protected` maps those beyond a calendar
    source's reach to the reason (see beyond_calendar_reach). A protected date is kept as it is, and a
    decided calendar date within NEAR_DAYS of it is the same report: absorbed, not inserted.
    """
    today = now.date()
    stored_by_date = {e.event_date: e for e in stored}
    stored_next = min(stored_by_date) if stored_by_date else None
    wanted = {f.day: f for f in decided}

    def _absorbed_by(day: date) -> date | None:
        near = [p for p in protected if abs((day - p).days) <= NEAR_DAYS]
        return min(near, key=lambda p: abs((day - p).days)) if near else None

    for f in decided:
        existing = stored_by_date.get(f.day)
        anchor = _absorbed_by(f.day)
        if anchor is not None:
            kept = stored_by_date[anchor]
            kept.checked_at = now
            plan.unchanged += 1
            if anchor != f.day:
                plan.kept.append(f"{ticker.symbol}: {f.day.isoformat()} ({f.source}) is the {anchor.isoformat()} report ({protected[anchor]}); not inserted")
                continue          # a different day: its time of day is not this date's
            if kept.report_timing == "unknown" and f.timing != "unknown":
                kept.report_timing = f.timing
                kept.report_timing_source = f.source
            await _upsert_timing(session, ticker.id, anchor, f.timing, f.source)
            continue
        if existing is None:
            session.add(Event(
                ticker_id=ticker.id, event_type=EventType.EARNINGS, event_date=f.day, title=f"{ticker.symbol} Earnings",
                source=SOURCE_ENUM[f.source], is_confirmed=f.confirmed, confirmation_note=f.note, checked_at=now,
                metadata_={}, report_timing=f.timing, report_timing_source=f.source if f.timing != "unknown" else "unknown",
            ))
            plan.inserted.append(f"{ticker.symbol}: {f.day.isoformat()} {f.note}")
        else:
            was_confirmed = existing.is_confirmed
            existing.source = SOURCE_ENUM[f.source]
            existing.is_confirmed = f.confirmed
            existing.confirmation_note = f.note
            existing.checked_at = now
            existing.unresolved_since = None
            existing.sources_checked = None
            if existing.report_timing == "unknown" and f.timing != "unknown":
                existing.report_timing = f.timing
                existing.report_timing_source = f.source
            plan.unchanged += 1
            if f.confirmed and not was_confirmed:
                plan.confirmed.append(f"{ticker.symbol}: {f.day.isoformat()} {f.note}")
        if f.confirmed and existing is None:
            plan.confirmed.append(f"{ticker.symbol}: {f.day.isoformat()} {f.note}")
        await _upsert_timing(session, ticker.id, f.day, f.timing, f.source)

    after = {f.day for f in decided if _absorbed_by(f.day) is None} | set(protected)
    next_after = min(after) if after else None
    for e in stored:
        if e.event_date in wanted:
            continue
        if e.event_date in protected:
            lists = "calendar sources list " + ", ".join(d.isoformat() for d in sorted(wanted)) if wanted else "no calendar source lists it"
            plan.kept.append(f"{ticker.symbol}: kept {e.event_date.isoformat()} ({protected[e.event_date]}); {lists}")
            e.checked_at = now
            continue
        lists = f"sources list {next_after.isoformat()}" if next_after else "no source lists a date"
        plan.dropped.append(f"{ticker.symbol}: dropped {e.event_date.isoformat()} ({getattr(e.source, 'value', e.source)}); {lists}")
        await session.delete(e)
    if stored_next and next_after and stored_next != next_after:
        plan.replaced.append(f"{ticker.symbol}: {stored_next.isoformat()} -> {next_after.isoformat()}")

    for e, res in past:
        label = f"{ticker.symbol}: {e.event_date.isoformat()} {res.note}"
        if res.action == "superseded":
            plan.superseded.append(label)
            await session.delete(e)
        elif res.action == "reported":
            e.event_date = res.report_date
            e.is_confirmed = True
            e.confirmation_note = res.note
            e.unresolved_since = None
            e.sources_checked = None
            e.checked_at = now
            plan.reported.append(label)
        else:
            e.unresolved_since = e.unresolved_since or today
            e.sources_checked = res.sources_checked
            e.confirmation_note = res.note
            e.is_confirmed = False
            e.checked_at = now
            plan.unresolved.append(label)

    if not decided and not protected:
        plan.no_date.append(ticker.symbol)
    ticker.earnings_checked_at = now
    plan.checked += 1


async def reconcile(session, tickers: list[Ticker], sources: dict, now: datetime, edgar: EdgarClient | None = None) -> Plan:
    """Decide and apply for every ticker. `sources` carries what the fetch phase found (see main)."""
    today = now.date()
    plan = Plan()
    for ticker in tickers:
        sym = ticker.symbol
        fin_future = sources["finnhub_future"].get(sym, {})
        yf_future = sources["yfinance_future"].get(sym, {})
        company = sources["company"].get(sym)
        cands = [Candidate(d, "finnhub", t) for d, t in fin_future.items()]
        cands += [Candidate(d, "yfinance", t) for d, t in yf_future.items()]
        if company is not None:
            cands.append(Candidate(company.day, "company", company.timing, company.evidence))

        reactions = sorted((await session.execute(
            select(HistoricalReaction.event_date).where(
                HistoricalReaction.ticker_id == ticker.id, HistoricalReaction.event_type == EventType.EARNINGS)
        )).scalars().all())

        actuals = sources["finnhub_actual"].get(sym, []) + sources["yfinance_reported"].get(sym, [])
        stored = list((await session.execute(
            select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date >= today)
            .order_by(Event.event_date)
        )).scalars().all())
        protected: dict[date, str] = {}
        for e in stored:
            reason = beyond_calendar_reach(_stored_date(e), reactions, actuals)
            if reason:
                protected[e.event_date] = reason

        # the last report: the newest reaction row, or today's report if its evidence is already stored
        reported = reactions + [d for d in protected if d <= today]
        last_report = max(reported) if reported else None
        decided = merge_future(cands, last_report, today)

        past_estimates = list((await session.execute(
            select(Event).where(
                Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.is_confirmed.is_(False),
                Event.event_date < today, Event.event_date >= today - timedelta(days=PAST_LOOKBACK_DAYS))
        )).scalars().all())
        past: list[tuple[Event, PastResolution]] = []
        for e in past_estimates:
            if beyond_calendar_reach(_stored_date(e), reactions, []):
                continue   # it has its row or a non-calendar source: the calendar step leaves it alone
            edgar_202: list[date] = []
            if edgar is not None and (today - e.event_date).days <= EDGAR_202_LOOKBACK_DAYS + 5:
                edgar_202 = await _edgar_202_dates(edgar, sym, today)
            res = resolve_past(
                e.event_date, today, reactions, [f.day for f in decided],
                sources["finnhub_actual"].get(sym, []), sources["yfinance_reported"].get(sym, []), edgar_202, now,
            )
            past.append((e, res))

        await apply_ticker(session, ticker, stored, protected, decided, past, now, plan)
    await session.commit()
    return plan


def _stored_date(e: Event) -> StoredDate:
    return StoredDate(e.event_date, getattr(e.source, "value", e.source), bool(e.is_confirmed), e.confirmation_note)


async def _edgar_202_dates(edgar: EdgarClient, sym: str, today: date) -> list[date]:
    try:
        cik = await edgar.get_cik(sym)
        if not cik:
            return []
        out = []
        for r in await edgar.get_all_8k_records(cik):
            items = [i.strip() for i in (r.get("items") or "").split(",")]
            if "2.02" in items:
                try:
                    d = date.fromisoformat(r["filing_date"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (today - d).days <= 30:
                    out.append(d)
        return out
    except Exception as exc:
        print(f"  EDGAR 2.02 check skipped for {sym}: {exc}", flush=True)
        return []


async def fetch_announcements(finnhub: FinnhubClient, edgar: EdgarClient, symbols: list[str], today: date, budget_s: float) -> dict:
    """{symbol: Announcement} from Finnhub news and EDGAR 8-K 7.01/8.01, inside a budget."""
    out: dict = {}
    started = time.monotonic()
    since = (today - timedelta(days=45)).isoformat()
    for sym in symbols:
        if time.monotonic() - started > budget_s:
            print(f"  announcements: budget of {budget_s:.0f}s reached after {len(out)} found in {symbols.index(sym)} tickers", flush=True)
            break
        try:
            hit = from_news(await finnhub.get_company_news(sym, since, today.isoformat()), today)
            if hit is None:
                cik = await edgar.get_cik(sym)
                if cik:
                    for r in edgar_ir_8ks(await edgar.get_all_8k_records(cik), today)[:3]:
                        html = await edgar.fetch_filing_html(cik, r["accession"], r.get("primary_document") or r.get("primaryDocument", ""))
                        from bs4 import BeautifulSoup
                        text = BeautifulSoup(html, "html.parser").get_text(" ")
                        hit = from_8k_text(text, r["filing_date"], r.get("items", ""), today)
                        if hit:
                            break
        except Exception as exc:
            print(f"  announcement check skipped for {sym}: {exc}", flush=True)
            continue
        if hit is not None:
            out[sym] = hit
    return out


async def main() -> int:
    now = datetime.now(timezone.utc)
    today = now.date()

    finnhub = FinnhubClient()
    edgar = EdgarClient()
    try:
        raw = await finnhub.get_earnings_calendar((today - timedelta(days=PAST_LOOKBACK_DAYS)).isoformat(),
                                                  (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat())
        entries = raw.get("earningsCalendar", [])
        print(f"Finnhub returned {len(entries)} calendar entries.")
        if not entries:
            print("Finnhub returned no entries; nothing changed and no ticker marked checked.")
            await record_step_fields(STEP_LABEL, {"checked": 0, "error": "Finnhub returned no calendar entries"})
            return 1
        fin_future, fin_actual = finnhub_by_symbol(entries, today)

        async with ScriptSessionLocal() as session:
            tickers = list((await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all())
        symbols = [t.symbol for t in tickers]

        yf_future, yf_reported, reached = await yfinance_by_symbol(symbols, YFINANCE_BUDGET_SECONDS)
        print(f"Yahoo Finance reached {len(reached)} of {len(symbols)} tickers.")

        near = sorted({s for s in symbols for d in list(fin_future.get(s, {})) + list(yf_future.get(s, {}))
                       if (d - today).days <= ANNOUNCE_WINDOW_DAYS})
        company = await fetch_announcements(finnhub, edgar, near, today, ANNOUNCE_BUDGET_SECONDS)
        print(f"Company announcements: {len(company)} found among {len(near)} tickers reporting within {ANNOUNCE_WINDOW_DAYS} days.")

        sources = {"finnhub_future": fin_future, "finnhub_actual": fin_actual,
                   "yfinance_future": yf_future, "yfinance_reported": yf_reported, "company": company}
        async with ScriptSessionLocal() as session:
            tickers = list((await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all())
            plan = await reconcile(session, tickers, sources, now, edgar)
        plan.yfinance_reached = len(reached)
        plan.announcements_checked = len(near)
    finally:
        await finnhub.close()
        await edgar.close()

    print(f"\n{'─' * 60}")
    print(f"  Checked {plan.checked}  Inserted {len(plan.inserted)}  Replaced {len(plan.replaced)}  Dropped {len(plan.dropped)}  "
          f"Kept {len(plan.kept)}  Confirmed {len(plan.confirmed)}  Reported {len(plan.reported)}  Superseded {len(plan.superseded)}  "
          f"Unresolved {len(plan.unresolved)}  No date {len(plan.no_date)}")
    print(f"{'─' * 60}")
    for title, rows in (("Confirmed", plan.confirmed), ("Replaced", plan.replaced), ("Unresolved", plan.unresolved),
                        ("Reported", plan.reported), ("Superseded", plan.superseded), ("Dropped", plan.dropped), ("Kept", plan.kept)):
        if rows:
            print(f"\n  {title} (first 10):")
            print("\n".join(f"    {r}" for r in rows[:10]))
    await record_step_fields(STEP_LABEL, plan.fields())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
