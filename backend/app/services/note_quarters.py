"""A research note's inputs name one latest quarter, or the note is not served (Sam, 2026-10-29).

GOOG's note of 2026-10-29 was written the night after Alphabet reported: its text stated the new quarter's diluted EPS ($2.12, from
the 10-Q filed that day) while its figure strip still showed the July quarter ($9.11), whose reaction was the latest stored.
Each input names a quarter by its earnings report's date:

    strip   the latest stored earnings reaction (the strip's latest_quarter_date)
    eps     the latest earnings event on or before today with an EPS actual
    filing  the report of the 10-Q or 10-K the text was written from: the latest earnings event within FILING_AFTER_REPORT_DAYS
            before that filing's date (a 10-Q follows its quarter's release by days, at most weeks)

A note whose known inputs name different quarters is withheld (withheld_now), and the nightly never writes a new note while the
inputs disagree: the existing note stays up unchanged and the new one waits until every input names the same latest quarter.
A note written from now on stores its inputs (structured_content.inputs); an older one has them inferred from its strip, its
source filing and the stored events. An input that cannot be read is not counted as disagreeing.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

FILING_AFTER_REPORT_DAYS = 45
KEYS = ("strip", "eps", "filing")


def _day(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def filing_quarter(filing_date, report_dates: list[date]) -> date | None:
    """Pure: the report a 10-Q or 10-K belongs to: the latest report date within FILING_AFTER_REPORT_DAYS before its filing date."""
    f = _day(filing_date)
    if f is None:
        return None
    near = [d for d in report_dates if f - timedelta(days=FILING_AFTER_REPORT_DAYS) <= d <= f]
    return max(near, default=None)


def disagreement(inputs: dict | None) -> str | None:
    """Pure: why the inputs name different quarters ("strip 2026-07-22, eps 2026-10-28, filing 2026-10-28"), or None when every
    known input names the same one."""
    known = {k: _day((inputs or {}).get(k)) for k in KEYS}
    known = {k: v for k, v in known.items() if v is not None}
    if len(set(known.values())) <= 1:
        return None
    return ", ".join(f"{k} {v.isoformat()}" for k, v in known.items())


async def report_dates(db, ticker_id, today: date) -> tuple[list[date], date | None]:
    """(every earnings report date on or before today that the company confirmed or that has an actual, the latest with an EPS
    actual)."""
    rows = (await db.execute(text("""SELECT event_date, eps_actual IS NOT NULL AS has_eps FROM events WHERE ticker_id = :t AND event_type = 'earnings'
        AND event_date <= :d AND (is_confirmed OR eps_actual IS NOT NULL) ORDER BY event_date"""), {"t": ticker_id, "d": today})).all()
    return [r.event_date for r in rows], max((r.event_date for r in rows if r.has_eps), default=None)


async def strip_quarter(db, ticker_id) -> date | None:
    return (await db.execute(text("SELECT max(event_date) FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings'"),
                             {"t": ticker_id})).scalar()


async def current_inputs(db, ticker_id, filing_date, today: date | None = None) -> dict:
    """What a note written now would rest on: {strip, eps, filing} as ISO dates (or None)."""
    today = today or date.today()
    dates, eps = await report_dates(db, ticker_id, today)
    strip = await strip_quarter(db, ticker_id)
    filing = filing_quarter(filing_date, dates)
    return {"strip": strip.isoformat() if strip else None, "eps": eps.isoformat() if eps else None, "filing": filing.isoformat() if filing else None}


async def note_inputs(db, note) -> dict:
    """A stored note's inputs: its own record, or inferred from its strip, its source filing and the events stored before it."""
    sc = note.structured_content or {}
    if isinstance(sc.get("inputs"), dict):
        return sc["inputs"]
    written = (note.generated_at.date() if note.generated_at else None) or date.today()
    dates, eps = await report_dates(db, note.ticker_id, written)
    filed = next((f.get("filing_date") for f in (note.source_filings or []) if isinstance(f, dict) and f.get("filing_date")), None)
    stats = sc.get("stats") if isinstance(sc.get("stats"), dict) else {}
    filing = filing_quarter(filed, dates)
    return {"strip": stats.get("latest_quarter_date"), "eps": eps.isoformat() if eps else None, "filing": filing.isoformat() if filing else None}


async def withheld_now(db, note) -> bool:
    """A visitor never sees this note: research_note_service.withheld, or its inputs name different quarters."""
    from app.services.research_note_service import is_verified, withheld
    if withheld(note):
        return True
    return is_verified(note) and disagreement(await note_inputs(db, note)) is not None
