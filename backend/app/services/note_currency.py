"""Whether a research note is still current: a note written before its company reported again describes a quarter that is no longer
the latest one, so the home page never shows it as current and every other page labels it "Written before the <date> report"
(MU's note of Sep 16, 2026 described the quarter reported Jun 24 after MU reported again on Sep 30).

A report counts when the stored record shows it happened: an earnings reaction row, or a confirmed earnings event on or before today.
A note generated on the report's own day counts as written before it (an after-the-close report post-dates a morning note).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import text

_LATEST_REPORT_SQL = text("""
    SELECT max(d) FROM (
        SELECT event_date AS d FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings'
        UNION ALL
        SELECT event_date FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND is_confirmed AND event_date <= :today
    ) x WHERE d >= :since AND d <= :today""")


def note_day(generated_at: datetime) -> date:
    return generated_at.date()


async def report_since(db, ticker_id: uuid.UUID, generated_at: datetime | None, today: date | None = None) -> date | None:
    """The newest earnings report on or after the note's generation day, or None when the note is still current."""
    if generated_at is None:
        return None
    today = today or date.today()
    return (await db.execute(_LATEST_REPORT_SQL, {"t": ticker_id, "since": note_day(generated_at), "today": today})).scalar()
