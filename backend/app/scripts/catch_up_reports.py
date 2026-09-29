"""Catch reports the calendar missed: a report that happened with no reaction row.

The seeder only learns about a report from the events table, so a report whose
date was never stored (or stored wrong) is never measured. This step asks the
sources that know a report happened: Finnhub's past earnings calendar (an entry
with an actual EPS) for every active ticker, and EDGAR (an 8-K carrying Item
2.02, the earnings release) for tickers Finnhub does not list whose report was
expected in the window: a stored earnings date fell inside it, or the last
reaction row is REPORT_DUE_DAYS or more old, so a quarterly report was due whether
or not the calendar still holds a date for it. For each report in the last
LOOKBACK_DAYS with no reaction row within MATCH_TOLERANCE_DAYS of it:

  - the events row is inserted or confirmed, so the ordinary seeder path sees it;
  - if the report is at least MIN_AGE_DAYS old (the 5-day reaction window has
    settled), the ticker is re-seeded now: caught_up, or unseedable with the
    reason (Yahoo has no such date);
  - otherwise it is pending: it will be seeded once the window settles.

Usage
-----
    python -m app.scripts.catch_up_reports            # write: events + reactions
    python -m app.scripts.catch_up_reports --report   # read only: list what is missing
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.edgar_client import EdgarClient
from app.services.finnhub_client import FinnhubClient
from app.services.step_outcomes import record_step_fields

LOOKBACK_DAYS = 21
MATCH_TOLERANCE_DAYS = 2      # a row within this many days of the report date counts as the report's row
REPORT_DUE_DAYS = 80          # no reaction row this recent: a quarterly report was due, check EDGAR even with no stored date
STEP_LABEL = "Missed reports (catch_up_reports)"
EDGAR_EARNINGS_ITEM = "2.02"  # Results of Operations and Financial Condition


@dataclass
class Missing:
    symbol: str
    report_date: date
    source: str          # "finnhub" | "edgar"
    age_days: int
    status: str = ""     # caught_up | pending | unseedable | found (report mode)
    detail: str = ""

    def label(self) -> str:
        return f"{self.symbol}@{self.report_date.isoformat()}"


# ── Sources ──────────────────────────────────────────────────────────────────

def finnhub_reports(entries: list[dict], today: date, lookback_days: int = LOOKBACK_DAYS) -> dict[str, list[date]]:
    """{symbol: [report dates]} for calendar entries in the window that carry an actual EPS."""
    start = today - timedelta(days=lookback_days)
    out: dict[str, list[date]] = {}
    for e in entries:
        sym = e.get("symbol")
        try:
            d = date.fromisoformat(e["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not sym or d < start or d > today or e.get("epsActual") is None:
            continue
        out.setdefault(sym, []).append(d)
    return out


def edgar_release_dates(records: list[dict], today: date, lookback_days: int = LOOKBACK_DAYS) -> list[date]:
    """Filing dates of 8-Ks carrying Item 2.02 inside the window."""
    start = today - timedelta(days=lookback_days)
    out: list[date] = []
    for r in records:
        items = [i.strip() for i in (r.get("items") or "").split(",")]
        if EDGAR_EARNINGS_ITEM not in items:
            continue
        try:
            d = date.fromisoformat(r["filing_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= d <= today:
            out.append(d)
    return sorted(set(out))


# ── Matching ─────────────────────────────────────────────────────────────────

def missing_reports(reported: dict[str, list[tuple[date, str]]], rows: dict[str, list[date]], today: date,
                    tolerance_days: int = MATCH_TOLERANCE_DAYS) -> list[Missing]:
    """Reports with no reaction row within the tolerance. `reported` is {sym: [(date, source)]}."""
    out: list[Missing] = []
    for sym, reports in sorted(reported.items()):
        have = rows.get(sym, [])
        for d, source in sorted(set(reports)):
            if any(abs((d - r).days) <= tolerance_days for r in have):
                continue
            out.append(Missing(symbol=sym, report_date=d, source=source, age_days=(today - d).days))
    return out


async def _reaction_dates(session, ticker_ids: dict[str, object], start: date) -> dict[str, list[date]]:
    id_to_sym = {v: k for k, v in ticker_ids.items()}
    rows = (await session.execute(
        select(HistoricalReaction.ticker_id, HistoricalReaction.event_date).where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.ticker_id.in_(list(ticker_ids.values())),
            HistoricalReaction.event_date >= start - timedelta(days=MATCH_TOLERANCE_DAYS),
        )
    )).all()
    out: dict[str, list[date]] = {}
    for tid, d in rows:
        out.setdefault(id_to_sym[tid], []).append(d)
    return out


async def _expected_in_window(session, ticker_ids: dict[str, object], start: date, today: date) -> set[str]:
    """Tickers we expected to report in the window: a stored earnings date fell inside it, or the last
    reaction row is REPORT_DUE_DAYS or more old (a quarterly report was due), so a date the calendar
    dropped or never held does not hide the report."""
    id_to_sym = {v: k for k, v in ticker_ids.items()}
    rows = (await session.execute(
        select(Event.ticker_id).where(
            Event.event_type == EventType.EARNINGS,
            Event.ticker_id.in_(list(ticker_ids.values())),
            Event.event_date >= start, Event.event_date <= today,
        ).distinct()
    )).all()
    expected = {id_to_sym[r[0]] for r in rows}
    recent = (await session.execute(
        select(HistoricalReaction.ticker_id).where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.ticker_id.in_(list(ticker_ids.values())),
            HistoricalReaction.event_date > today - timedelta(days=REPORT_DUE_DAYS),
        ).distinct()
    )).all()
    with_recent_row = {id_to_sym[r[0]] for r in recent}
    return expected | (set(ticker_ids) - with_recent_row)


# ── Writes ───────────────────────────────────────────────────────────────────

async def _ensure_event(session, ticker_id, d: date, source: str) -> str:
    """Insert or confirm the events row for a report that happened. Returns what was done."""
    existing = (await session.execute(
        select(Event).where(
            Event.ticker_id == ticker_id, Event.event_type == EventType.EARNINGS,
            Event.event_date >= d - timedelta(days=MATCH_TOLERANCE_DAYS),
            Event.event_date <= d + timedelta(days=MATCH_TOLERANCE_DAYS),
        ).order_by(Event.event_date)
    )).scalars().first()
    src = DataSource.FINNHUB if source == "finnhub" else DataSource.EDGAR
    note = f"reported on {d.isoformat()} per " + ("Finnhub (actual EPS)" if source == "finnhub" else "EDGAR (8-K Item 2.02)")
    now = datetime.now(timezone.utc)
    if existing is None:
        session.add(Event(ticker_id=ticker_id, event_type=EventType.EARNINGS, event_date=d, title="Earnings", source=src,
                          is_confirmed=True, confirmation_note=note, checked_at=now, metadata_={}))
        return "event inserted"
    changed = []
    if existing.event_date != d:
        changed.append(f"date {existing.event_date.isoformat()} -> {d.isoformat()}")
        existing.event_date = d
        existing.source = src
    if not existing.is_confirmed:
        existing.is_confirmed = True
        existing.source = src
        existing.confirmation_note = note
        existing.unresolved_since = None
        existing.sources_checked = None
        changed.append("confirmed")
    if changed:
        existing.checked_at = now
    return "event " + ", ".join(changed) if changed else "event already right"


async def catch_up(missing: list[Missing], ticker_ids: dict[str, object], write: bool) -> None:
    """Fill each Missing.status. With write=False nothing is touched and every status is 'found'."""
    from app.scripts.seed_historical_reactions import MIN_AGE_DAYS, seed

    if not write:
        for m in missing:
            m.status = "found"
            m.detail = "settled, seedable now" if m.age_days >= MIN_AGE_DAYS else f"reaction window not settled ({MIN_AGE_DAYS - m.age_days} more days)"
        return

    async with ScriptSessionLocal() as session:
        for m in missing:
            m.detail = await _ensure_event(session, ticker_ids[m.symbol], m.report_date, m.source)
        await session.commit()

    for sym in sorted({m.symbol for m in missing if m.age_days >= MIN_AGE_DAYS}):
        await seed(sym)   # re-reads Yahoo's earnings dates and upserts every reaction for the ticker
    async with ScriptSessionLocal() as session:
        rows = await _reaction_dates(session, ticker_ids, date.today() - timedelta(days=LOOKBACK_DAYS))
    for m in missing:
        if m.age_days < MIN_AGE_DAYS:
            m.status = "pending"
            m.detail += f"; reaction window not settled ({MIN_AGE_DAYS - m.age_days} more days)"
        elif any(abs((m.report_date - r).days) <= MATCH_TOLERANCE_DAYS for r in rows.get(m.symbol, [])):
            m.status = "caught_up"
        else:
            m.status = "unseedable"
            m.detail += "; Yahoo lists no earnings date near it, so the seeder wrote no row"


# ── Main ─────────────────────────────────────────────────────────────────────

async def find_missing(session, tickers: list, entries: list[dict], edgar: EdgarClient | None, today: date) -> list[Missing]:
    start = today - timedelta(days=LOOKBACK_DAYS)
    ticker_ids = {t.symbol: t.id for t in tickers}
    reported: dict[str, list[tuple[date, str]]] = {}
    for sym, dates in finnhub_reports(entries, today).items():
        if sym in ticker_ids:
            reported[sym] = [(d, "finnhub") for d in dates]

    # EDGAR only where we expected a report and Finnhub says nothing: a handful of calls
    if edgar is not None:
        expected = await _expected_in_window(session, ticker_ids, start, today)
        for sym in sorted(expected - set(reported)):
            try:
                cik = await edgar.get_cik(sym)
                if not cik:
                    continue
                dates = edgar_release_dates(await edgar.get_all_8k_records(cik), today)
            except Exception as exc:   # one filer must not stop the check
                print(f"  EDGAR check skipped for {sym}: {exc}", flush=True)
                continue
            if dates:
                reported[sym] = [(d, "edgar") for d in dates]

    rows = await _reaction_dates(session, ticker_ids, start)
    return missing_reports(reported, rows, today)


async def main(argv: list[str]) -> int:
    write = "--report" not in argv
    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)

    finnhub = FinnhubClient()
    try:
        raw = await finnhub.get_earnings_calendar(start.isoformat(), today.isoformat())
    finally:
        await finnhub.close()
    entries = raw.get("earningsCalendar", [])
    print(f"Finnhub: {len(entries)} calendar entries for {start} .. {today}.")

    edgar = EdgarClient()
    try:
        async with ScriptSessionLocal() as session:
            # id and symbol only: the check must run against a database that predates newer ticker columns
            tickers = list((await session.execute(
                select(Ticker.id, Ticker.symbol).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).all())
            missing = await find_missing(session, tickers, entries, edgar, today)
    finally:
        await edgar.close()

    ticker_ids = {t.symbol: t.id for t in tickers}
    await catch_up(missing, ticker_ids, write)

    print(f"\n{'─' * 60}")
    print(f"  {len(tickers)} active tickers checked; {len(missing)} report(s) in the last {LOOKBACK_DAYS} days with no reaction row"
          + ("" if write else " (report only, nothing written)"))
    print(f"{'─' * 60}")
    for m in missing:
        print(f"  {m.symbol:<6} {m.report_date}  {m.age_days:>2}d ago  via {m.source:<7} {m.status:<10} {m.detail}")

    if write:
        by = {s: [m.label() for m in missing if m.status == s] for s in ("caught_up", "pending", "unseedable")}
        await record_step_fields(STEP_LABEL, {
            "checked": len(tickers), "missing": len(missing),
            "caught_up": by["caught_up"], "pending": by["pending"], "unseedable": by["unseedable"],
            "details": {m.label(): m.detail for m in missing},
        })
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
