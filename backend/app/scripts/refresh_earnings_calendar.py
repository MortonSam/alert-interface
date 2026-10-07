"""Refresh the earnings calendar: every source, every active ticker, every run, with a confirmation level.

Sources, per run:
  Finnhub   one /calendar/earnings call, today-60 .. today+LOOKAHEAD_DAYS: future estimates and, in the
            past part, which reports carried an actual EPS.
  Yahoo     per-ticker earnings_dates (future estimates with their time of day; reported EPS for the past),
            paced in a thread pool inside YFINANCE_BUDGET_SECONDS, unanswered tickers asked once more; the
            pass asks tickers not reached in recent runs first, then rotates its start daily, and the outcome
            records which tickers were not reached and for how many runs in a row.
  Company   Finnhub company news and EDGAR 8-K Items 7.01/8.01 (report_announcements) for tickers whose
            nearest candidate is within ANNOUNCE_WINDOW_DAYS: the one source that confirms a date.
  EDGAR     8-K Item 2.02 for an estimate that passed in the last few days with no report found.

Decisions are earnings_calendar.merge_future / resolve_past / beyond_calendar_reach / standing_candidates
(pure, tested); this script fetches and applies. A stored date beyond a calendar source's reach (a reaction
row, an actual EPS, an EDGAR source, a company announcement) is kept as it is whatever Finnhub or Yahoo
list, and a calendar date within SAME_REPORT_DAYS of it is the same report and is not inserted beside it.
An empty or failed fetch is never evidence: a stored estimate whose source returned no future date for the
ticker stands as that source's word, so the Yahoo budget running out (the pass starts at a different
ticker each day) or a ticker missing from Finnhub's calendar drops nothing. Every active ticker's
earnings_checked_at is set whether or not a date came back.

Usage
-----
    python -m app.scripts.refresh_earnings_calendar
"""
from __future__ import annotations
from app.services.redact import redact

import asyncio
import sys
import time

import httpx
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func as sa_func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy import text as sa_text

from app.database import ScriptSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.earnings_calendar import (
    CALENDAR_SOURCES, EDGAR_202_LOOKBACK_DAYS, SAME_REPORT_DAYS, SOURCE_LABELS, Candidate, FutureDate, PastResolution,
    StoredDate, beyond_calendar_reach, far_note, merge_future, resolve_past, standing_candidates,
)
from app.services.edgar_client import EdgarClient
from app.services.finnhub_client import FinnhubClient
from app.services.report_announcements import edgar_ir_8ks, from_8k_text, from_news
from app.services.system_metadata_service import get_value, set_value
from app.services.step_outcomes import record_step_fields

LOOKAHEAD_DAYS = 120
PAST_LOOKBACK_DAYS = 60          # past estimated events this old are re-resolved
# Measured 2026-09-30 from the backend container, 512 active tickers: 6 workers with no pause finished in 58 s but
# Yahoo answered only 377 (it serves pages without the earnings table once a burst is sustained; the misses came in
# blocks); 3 workers with 0.3 s between batches answered 60 of 60 at 0.35 s per ticker, so a full pass is ~180 s.
# The budget covers a full paced pass, the 30 s retry pause and a retry of every miss, with margin.
YFINANCE_BUDGET_SECONDS = 420
YFINANCE_WORKERS = 3
YFINANCE_PAUSE_SECONDS = 0.3
YFINANCE_RETRY_PAUSE_SECONDS = 30
UNREACHED_RUNS_WARN = 3          # a ticker Yahoo has not answered for this many runs in a row is named in the outcome
ANNOUNCE_WINDOW_DAYS = 60        # look for a company announcement when the nearest candidate or stored date is this close
IR_FEED_WINDOW_DAYS = 60         # read the company's press-release feed when a candidate or stored date is this close
FEED_SPOTCHECK_KEY = "ir_feed_confirmations_started"   # system_metadata: the first night feed confirmations ran (the digest lists them for 7 nights)
ANNOUNCE_BUDGET_SECONDS = 240
REPORT_DUE_DAYS = 75             # no reaction row this recent: a report is due, ask for an announcement whatever the calendar says
STEP_LABEL = "Refresh earnings calendar (Finnhub)"
SOURCE_ENUM = {"finnhub": DataSource.FINNHUB, "yfinance": DataSource.YFINANCE, "company": DataSource.EDGAR}


@dataclass
class Plan:
    checked: int = 0
    inserted: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)        # beyond a calendar source's reach, whatever the sources list
    standing: list[str] = field(default_factory=list)    # a stored estimate whose source returned nothing this run
    confirmed: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    reported: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    feeds_read: int = 0                                           # press-release feeds read this run (services/ir_feeds)
    feed_hits: int = 0                                            # announcements found in them
    feed_confirmations: list[dict] = field(default_factory=list)  # {symbol, date, link, title} confirmed from a feed this run
    feed_spotcheck_started: str | None = None                     # the first night feed confirmations ran (digest lists them for 7 nights)
    unchanged: int = 0
    no_date: list[str] = field(default_factory=list)
    yfinance_reached: int = 0
    yfinance_silent: int = 0          # active tickers Yahoo gave no future date for (not reached, failed, or none listed)
    yfinance_started_at: str = ""     # the symbol the Yahoo pass started from
    yfinance_seconds: float = 0.0
    yfinance_unreached: list[str] = field(default_factory=list)      # not asked (budget) or no answer this run
    yfinance_unreached_streak: dict = field(default_factory=dict)    # {symbol: runs in a row unreached}, from the last outcome
    announcements_checked: int = 0
    announcements_found: int = 0

    def fields(self) -> dict:
        return {
            "checked": self.checked, "inserted": len(self.inserted), "replaced": len(self.replaced),
            "dropped": len(self.dropped), "kept": len(self.kept), "standing": len(self.standing),
            "confirmed": len(self.confirmed), "unresolved": len(self.unresolved),
            "reported": len(self.reported), "superseded": len(self.superseded), "unchanged": self.unchanged,
            "feeds_read": self.feeds_read, "feed_hits": self.feed_hits, "feed_confirmations": self.feed_confirmations,
            "feed_spotcheck_started": self.feed_spotcheck_started,
            "no_date": len(self.no_date), "yfinance_reached": self.yfinance_reached, "yfinance_silent": self.yfinance_silent,
            "yfinance_started_at": self.yfinance_started_at, "yfinance_seconds": round(self.yfinance_seconds, 1),
            "yfinance_unreached": self.yfinance_unreached, "yfinance_unreached_streak": self.yfinance_unreached_streak,
            "yfinance_unreached_3_runs": sorted(s for s, n in self.yfinance_unreached_streak.items() if n >= UNREACHED_RUNS_WARN),
            "announcements_checked": self.announcements_checked, "announcements_found": self.announcements_found,
            "unresolved_list": self.unresolved[:50], "confirmed_examples": self.confirmed[:10],
            "replaced_examples": self.replaced[:10], "dropped_examples": self.dropped[:10], "kept_examples": self.kept[:10],
            "standing_examples": self.standing[:10],
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


def _yf_fetch(symbol: str) -> tuple[dict[date, str], list[date]] | None:
    """Sync: ({future date: timing}, [past dates with a reported EPS]) from Yahoo's earnings_dates; None if nothing came back."""
    import math
    import yfinance as yf
    df = yf.Ticker(symbol).get_earnings_dates(limit=12)
    future: dict[date, str] = {}
    reported: list[date] = []
    if df is None or df.empty:
        return None          # no answer, not an answer of "no dates"
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


def yfinance_order(symbols: list[str], today: date, streak: dict | None = None) -> list[str]:
    """The order the Yahoo pass asks in: tickers not reached in recent runs first, longest streak first, then the
    rest starting at a different ticker each day. A run that reaches at least a third of the tickers therefore asks
    every ticker within three runs (tested); a ticker Yahoo never answers for is asked first every run and counted."""
    if not symbols:
        return []
    streak = streak or {}
    first = sorted((s for s in symbols if streak.get(s)), key=lambda s: (-int(streak[s]), s))
    rest = [s for s in symbols if s not in set(first)]
    start = today.toordinal() % len(rest) if rest else 0
    return first + rest[start:] + rest[:start]


def unreached_streak(previous: dict, unreached_now: list[str]) -> dict:
    """{symbol: runs in a row unreached}: the last run's streak plus one for each still unreached, others cleared."""
    return {s: int(previous.get(s, 0)) + 1 for s in unreached_now}


async def _last_outcome(label: str) -> dict:
    """The fields this step recorded last run, or {}."""
    import json
    from app.services.system_metadata_service import get_value
    try:
        async with ScriptSessionLocal() as session:
            raw = await get_value(session, "step_outcomes")
        return (json.loads(raw) if raw else {}).get(label) or {}
    except Exception as exc:
        print(f"  [WARN] could not read the last outcome for {label}: {redact(exc)}", flush=True)
        return {}


async def yfinance_by_symbol(symbols: list[str], budget_s: float | None) -> tuple[dict[str, dict[date, str]], dict[str, list[date]], set[str]]:
    """Per-ticker Yahoo fetch inside a budget (None: no budget). Returns (future, reported, reached).

    A ticker is reached only when Yahoo answered with rows; an exception or an empty frame leaves it out, and
    the calendar treats it as unanswered (its stored estimate stands). Yahoo throttles bursts by serving pages
    without the earnings table, so batches are paced (YFINANCE_WORKERS at a time, YFINANCE_PAUSE_SECONDS between)
    and, when budget remains, the tickers it did not answer are asked once more after YFINANCE_RETRY_PAUSE_SECONDS."""
    loop = asyncio.get_event_loop()
    future: dict[str, dict[date, str]] = {}
    reported: dict[str, list[date]] = {}
    reached: set[str] = set()
    started = time.monotonic()

    def remaining() -> float | None:
        return None if budget_s is None else budget_s - (time.monotonic() - started)

    async def one_pass(todo: list[str], label: str) -> None:
        with ThreadPoolExecutor(max_workers=YFINANCE_WORKERS) as pool:
            for i in range(0, len(todo), YFINANCE_WORKERS):
                left = remaining()
                if left is not None and left <= 0:
                    print(f"  yfinance: budget of {budget_s:.0f}s reached after {len(reached)} tickers ({label})", flush=True)
                    return
                batch = todo[i:i + YFINANCE_WORKERS]
                results = await asyncio.gather(*[loop.run_in_executor(pool, _yf_fetch, s) for s in batch], return_exceptions=True)
                for sym, res in zip(batch, results):
                    if isinstance(res, Exception) or res is None:
                        continue
                    future[sym], reported[sym] = res
                    reached.add(sym)
                if YFINANCE_PAUSE_SECONDS:
                    await asyncio.sleep(YFINANCE_PAUSE_SECONDS)

    await one_pass(symbols, "first pass")
    missed = [s for s in symbols if s not in reached]
    left = remaining()
    if missed and (left is None or left > YFINANCE_RETRY_PAUSE_SECONDS + len(missed) * YFINANCE_PAUSE_SECONDS / YFINANCE_WORKERS):
        print(f"  yfinance: {len(missed)} tickers unanswered; asking again after {YFINANCE_RETRY_PAUSE_SECONDS}s", flush=True)
        await asyncio.sleep(YFINANCE_RETRY_PAUSE_SECONDS)
        await one_pass(missed, "retry")
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


def _stored_date(e: Event) -> StoredDate:
    return StoredDate(e.event_date, getattr(e.source, "value", e.source), bool(e.is_confirmed), e.confirmation_note,
                      e.report_timing or "unknown")


def _lists(days: list[date] | set[date]) -> str:
    return ", ".join(d.isoformat() for d in sorted(days))


async def apply_ticker(session, ticker: Ticker, stored: list[Event], protected: dict[date, str],
                       decided: list[FutureDate], past: list[tuple[Event, PastResolution]], now: datetime, plan: Plan,
                       answered: dict[str, set[date]] | None = None) -> None:
    """Write one ticker's decided future dates and past resolutions.

    `stored` is the ticker's stored dates on or after today; `protected` maps those beyond a calendar
    source's reach to the reason (see beyond_calendar_reach). A protected date is kept as it is, and a
    decided calendar date within SAME_REPORT_DAYS of it is the same report: absorbed, not inserted.
    `answered` maps each calendar source to the future dates it returned for the ticker (for the drop log).
    """
    today = now.date()
    answered = answered or {}
    stored_by_date = {e.event_date: e for e in stored}
    stored_next = min(stored_by_date) if stored_by_date else None
    wanted = {f.day: f for f in decided}

    def _absorbed_by(day: date) -> date | None:
        near = [p for p in protected if abs((day - p).days) < SAME_REPORT_DAYS]
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
            lists = "calendar sources list " + _lists(wanted) if wanted else "no calendar source lists it"
            plan.kept.append(f"{ticker.symbol}: kept {e.event_date.isoformat()} ({protected[e.event_date]}); {lists}")
            e.checked_at = now
            continue
        # only reachable when the date's own source now lists other dates, or a higher-precedence source
        # decided the report's day (standing_candidates keeps a silent source's estimate among the candidates)
        src = getattr(e.source, "value", e.source)
        same_report = [f for f in decided if abs((f.day - e.event_date).days) < SAME_REPORT_DAYS]
        if same_report:
            why = f"replaced by {same_report[0].day.isoformat()} ({SOURCE_LABELS.get(same_report[0].source, same_report[0].source)})"
        elif answered.get(src):
            why = f"{SOURCE_LABELS.get(src, src)} now lists {_lists(answered[src])}"
        else:
            why = "no source lists a date" if not next_after else f"sources list {next_after.isoformat()}"
        plan.dropped.append(f"{ticker.symbol}: dropped {e.event_date.isoformat()} ({src}); {why}")
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


async def reconcile(session, tickers: list[Ticker], sources: dict, now: datetime, edgar: EdgarClient | None = None,
                    write: bool = True) -> Plan:
    """Decide and apply for every ticker. `sources` carries what the fetch phase found (see run).
    With write=False the plan is computed against the database and rolled back: nothing is written."""
    today = now.date()
    plan = Plan()
    for ticker in tickers:
        sym = ticker.symbol
        fin_future = sources["finnhub_future"].get(sym, {})
        yf_future = sources["yfinance_future"].get(sym, {})
        company = sources["company"].get(sym)
        answered = {"finnhub": set(fin_future), "yfinance": set(yf_future)}
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

        # an empty or failed fetch is never evidence: a silent source's stored estimate is its standing word
        standing = standing_candidates([_stored_date(e) for e in stored if e.event_date not in protected],
                                       {src for src, days in answered.items() if days}, today)
        for c in standing:
            plan.standing.append(f"{sym}: {c.day.isoformat()} ({c.source}) stands; {SOURCE_LABELS[c.source]} returned no future date this run")
        cands += standing

        # the last report: the newest reaction row, or today's report if its evidence is already stored
        reported = reactions + [d for d in protected if d <= today]
        last_report = max(reported) if reported else None
        decided = merge_future(cands, None, today)
        if decided and (not protected or decided[0].day < min(protected)):
            note = far_note(decided[0].day, last_report)
            if note:
                decided[0].note += "; " + note

        past_estimates = list((await session.execute(
            select(Event).where(
                Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.is_confirmed.is_(False),
                Event.event_date < today, Event.unresolved_since.is_(None) | (Event.event_date >= today - timedelta(days=PAST_LOOKBACK_DAYS)))
            # every past estimate still standing as resolved is re-judged, however old (FDX's June 2026 estimate stood for
            # months beyond the lookback); one already marked unresolved is re-asked only inside the lookback
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

        await apply_ticker(session, ticker, stored, protected, decided, past, now, plan, answered)
    if write:
        await session.commit()
    else:
        await session.rollback()
    return plan


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
        print(f"  EDGAR 2.02 check skipped for {sym}: {redact(exc)}", flush=True)
        return []


# ── Announcements ────────────────────────────────────────────────────────────

def announcement_targets(symbols: list[str], fin_future: dict, yf_future: dict, stored_future: dict[str, list[date]],
                         last_report: dict[str, date], today: date) -> list[str]:
    """Tickers to ask for a company announcement: a candidate or stored date within ANNOUNCE_WINDOW_DAYS, or no
    reaction row in the last REPORT_DUE_DAYS (a report is due whatever the calendar holds)."""
    out = set()
    for s in symbols:
        days = list(fin_future.get(s, {})) + list(yf_future.get(s, {})) + list(stored_future.get(s, []))
        if any(0 <= (d - today).days <= ANNOUNCE_WINDOW_DAYS for d in days):
            out.add(s)
        elif s not in last_report or (today - last_report[s]).days >= REPORT_DUE_DAYS:
            out.add(s)
    return sorted(out)


async def fetch_announcements(finnhub: FinnhubClient, edgar: EdgarClient, symbols: list[str], today: date, budget_s: float | None,
                              names: dict[str, str] | None = None, feeds: dict[str, str] | None = None) -> dict:
    """{symbol: Announcement} from Finnhub news, the company's press-release feed (services/ir_feeds) and EDGAR 8-K 7.01/8.01,
    in that order, inside a budget.

    `names` maps symbol to the tickers table's company name: a news or feed item confirms only when its headline names the
    issuer (report_announcements.names_issuer). `feeds` maps symbol to the press-release feed to read (ir_feeds rows
    classified press_releases, for tickers with a candidate date within IR_FEED_WINDOW_DAYS). One log line per ticker says
    what each source returned."""
    from app.services import ir_feeds as F
    names = names or {}
    feeds = feeds or {}
    out: dict = {}
    started = time.monotonic()
    since = (today - timedelta(days=45)).isoformat()
    http = httpx.AsyncClient(headers={"User-Agent": F.UA})
    try:
        for sym in symbols:
            if budget_s is not None and time.monotonic() - started > budget_s:
                print(f"  announcements: budget of {budget_s:.0f}s reached after {len(out)} found in {symbols.index(sym)} tickers", flush=True)
                break
            try:
                news = await finnhub.get_company_news(sym, since, today.isoformat())
                hit = from_news(news, today, names.get(sym))
                said = [f"Finnhub news {len(news)} items" + ("" if hit else ", none from the issuer names a results date")]
                if hit is None and feeds.get(sym):
                    hit, read = await F.from_feed(http, feeds[sym], names.get(sym), today, sym)
                    said.append(read + ("" if hit else ", none names a results date"))
                if hit is None:
                    cik = await edgar.get_cik(sym)
                    if cik:
                        ir = edgar_ir_8ks(await edgar.get_all_8k_records(cik), today)[:3]
                        for r in ir:
                            html = await edgar.fetch_filing_html(cik, r["accession"], r.get("primary_document") or r.get("primaryDocument", ""))
                            from bs4 import BeautifulSoup
                            text = BeautifulSoup(html, "html.parser").get_text(" ")
                            hit = from_8k_text(text, r["filing_date"], r.get("items", ""), today)
                            if hit:
                                break
                        filings = ", ".join(f"{r['filing_date']} ({r.get('items', '')})" for r in ir) or "none"
                        said.append(f"EDGAR 8-K 7.01/8.01 since {since}: {filings}" + ("" if hit else "; none names a results date" if ir else ""))
                    else:
                        said.append("EDGAR: no CIK")
                print(f"  {sym}: " + "; ".join(said) + (f"; hit {hit.day.isoformat()} ({hit.evidence})" if hit else ""), flush=True)
            except Exception as exc:
                print(f"  announcement check skipped for {sym}: {redact(exc)}", flush=True)
                continue
            if hit is not None:
                out[sym] = hit
    finally:
        await http.aclose()
    return out


def feed_targets(symbols: list[str], fin_future: dict, yf_future: dict, stored_future: dict[str, list[date]], today: date,
                 feeds: dict[str, str]) -> dict[str, str]:
    """Pure: the press-release feeds to read tonight: tickers with a readable feed and a candidate or stored date within
    IR_FEED_WINDOW_DAYS."""
    out = {}
    for s in symbols:
        if s not in feeds:
            continue
        days = list(fin_future.get(s, {})) + list(yf_future.get(s, {})) + list(stored_future.get(s, []))
        if any(0 <= (d - today).days <= IR_FEED_WINDOW_DAYS for d in days):
            out[s] = feeds[s]
    return out


async def feed_confirmations_since(session, since: datetime) -> list[dict]:
    """Confirmations written this run whose evidence is the company's press-release feed: {symbol, date, link, title} for the digest."""
    rows = (await session.execute(
        select(Ticker.symbol, Event.event_date, Event.confirmation_note)
        .join(Ticker, Ticker.id == Event.ticker_id)
        .where(Event.event_type == EventType.EARNINGS, Event.is_confirmed.is_(True), Event.updated_at >= since,
               Event.confirmation_note.like("confirmed: press release via IR feed%"))
        .order_by(Event.event_date)
    )).all()
    from app.services.ir_feeds import release_link
    out = []
    for sym, d, note in rows:
        body = note.split(":", 2)[2].strip() if note.count(":") >= 2 else note
        out.append({"symbol": sym, "date": d.isoformat(), "link": release_link(note), "title": (body.rsplit(" http", 1)[0] if " http" in body else body)[:80]})
    return out


# ── Run ──────────────────────────────────────────────────────────────────────

async def run(yf_budget_s: float | None = YFINANCE_BUDGET_SECONDS, announce_budget_s: float | None = ANNOUNCE_BUDGET_SECONDS,
              write: bool = True, step_label: str | None = STEP_LABEL) -> int:
    """Fetch every source, decide, apply. Budgets of None mean every ticker; write=False computes and rolls back."""
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
            if step_label:
                await record_step_fields(step_label, outcome_fields({"checked": 0, "error": "Finnhub returned no calendar entries"}, 1, now))
            return 1
        fin_future, fin_actual = finnhub_by_symbol(entries, today)

        async with ScriptSessionLocal() as session:
            tickers = list((await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all())
            ids = {t.id: t.symbol for t in tickers}
            names = {t.symbol: t.name for t in tickers if t.name}
            rows = (await session.execute(
                select(HistoricalReaction.ticker_id, sa_func.max(HistoricalReaction.event_date))
                .where(HistoricalReaction.event_type == EventType.EARNINGS, HistoricalReaction.ticker_id.in_(list(ids)))
                .group_by(HistoricalReaction.ticker_id)
            )).all()
            last_report = {ids[tid]: d for tid, d in rows}
            rows = (await session.execute(
                select(Event.ticker_id, Event.event_date)
                .where(Event.event_type == EventType.EARNINGS, Event.ticker_id.in_(list(ids)), Event.event_date >= today)
            )).all()
            stored_future: dict[str, list[date]] = {}
            for tid, d in rows:
                stored_future.setdefault(ids[tid], []).append(d)
        symbols = [t.symbol for t in tickers]

        last = await _last_outcome(step_label) if step_label else {}
        order = yfinance_order(symbols, today, last.get("yfinance_unreached_streak") or {})
        started = time.monotonic()
        yf_future, yf_reported, reached = await yfinance_by_symbol(order, yf_budget_s)
        yf_seconds = time.monotonic() - started
        silent = [s for s in symbols if not yf_future.get(s)]
        unreached = [s for s in symbols if s not in reached]
        streak = unreached_streak(last.get("yfinance_unreached_streak") or {}, unreached)
        print(f"Yahoo Finance reached {len(reached)} of {len(symbols)} tickers in {yf_seconds:.0f}s (pass started at {order[0] if order else '-'}); "
              f"{len(unreached)} not reached, {len(silent)} with no future date from Yahoo: their stored Yahoo estimates stand.")
        stuck = sorted(s for s, n in streak.items() if n >= UNREACHED_RUNS_WARN)
        if stuck:
            print(f"  [WARN] not reached by Yahoo {UNREACHED_RUNS_WARN} runs in a row: {', '.join(stuck)}", flush=True)

        near = announcement_targets(symbols, fin_future, yf_future, stored_future, last_report, today)
        async with ScriptSessionLocal() as session:
            from app.services.ir_feeds import PRESS_RELEASES
            feed_rows = (await session.execute(sa_text("SELECT symbol, feed_url FROM ir_feeds WHERE feed_url IS NOT NULL AND classification = :c"),
                                               {"c": PRESS_RELEASES})).all()
        feeds = feed_targets(near, fin_future, yf_future, stored_future, today, {r[0]: r[1] for r in feed_rows})
        company = await fetch_announcements(finnhub, edgar, near, today, announce_budget_s, names, feeds)
        from_feeds = sum(1 for a in company.values() if "press release via IR feed" in a.evidence)
        print(f"Company announcements: {len(company)} found among {len(near)} tickers asked ({len(feeds)} press-release feeds read, {from_feeds} hits from them).")

        sources = {"finnhub_future": fin_future, "finnhub_actual": fin_actual,
                   "yfinance_future": yf_future, "yfinance_reported": yf_reported, "company": company}
        async with ScriptSessionLocal() as session:
            tickers = list((await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all())
            plan = await reconcile(session, tickers, sources, now, edgar, write=write)
        plan.yfinance_reached = len(reached)
        plan.yfinance_silent = len(silent)
        plan.yfinance_started_at = order[0] if order else ""
        plan.yfinance_seconds = yf_seconds
        plan.yfinance_unreached = unreached
        plan.yfinance_unreached_streak = streak
        plan.announcements_checked = len(near)
        plan.announcements_found = len(company)
        plan.feeds_read = len(feeds)
        plan.feed_hits = from_feeds
        if write:
            async with ScriptSessionLocal() as session:
                plan.feed_confirmations = await feed_confirmations_since(session, now)
                started = await get_value(session, FEED_SPOTCHECK_KEY)
                if started is None:
                    started = today.isoformat()
                    await set_value(session, FEED_SPOTCHECK_KEY, started)
                    await session.commit()
                plan.feed_spotcheck_started = started
    finally:
        await finnhub.close()
        await edgar.close()

    print(f"\n{'─' * 60}")
    print(f"  Checked {plan.checked}  Inserted {len(plan.inserted)}  Replaced {len(plan.replaced)}  Dropped {len(plan.dropped)}  "
          f"Kept {len(plan.kept)}  Standing {len(plan.standing)}  Confirmed {len(plan.confirmed)}  Reported {len(plan.reported)}  "
          f"Superseded {len(plan.superseded)}  Unresolved {len(plan.unresolved)}  No date {len(plan.no_date)}"
          + ("" if write else "   (dry run: rolled back, nothing written)"))
    print(f"{'─' * 60}")
    for title, rows in (("Confirmed", plan.confirmed), ("Replaced", plan.replaced), ("Unresolved", plan.unresolved),
                        ("Reported", plan.reported), ("Superseded", plan.superseded), ("Dropped", plan.dropped),
                        ("Kept", plan.kept), ("Standing", plan.standing), ("Inserted", plan.inserted)):
        if rows:
            limit = len(rows) if not write else 10
            print(f"\n  {title} ({'all' if limit == len(rows) else 'first 10'}):")
            print("\n".join(f"    {r}" for r in rows[:limit]))
    if write and step_label:
        await record_step_fields(step_label, outcome_fields(plan.fields(), 0, now))
    return 0


def outcome_fields(fields: dict, exit_code: int, started: datetime) -> dict:
    """The step's fields with exit, at and seconds: /health reads a missing exit as a failure, and a manual run
    (restore_yfinance_estimates) has no refresh.py wrapper to write them."""
    now = datetime.now(timezone.utc)
    from app.services.finnhub_client import finnhub_stats
    fields = {**fields, "finnhub": finnhub_stats()}
    return {**fields, "exit": exit_code, "at": now.isoformat(), "seconds": round((now - started).total_seconds(), 1)}


async def main() -> int:
    return await run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
