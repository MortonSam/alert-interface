"""Does the SEC acceptance time of a report's 8-K support the stored date or the refused one?

One rule, shared by the validate check and the repair script, built on
report_timing.acceptance_bucket: an acceptance explains an event date when it
falls pre-open, intraday or post-close relative to that date (or the next
morning before the open, for an after-close report). A filing that explains
the refused date and not the blocking one is evidence for a swap; anything
less is not.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.report_timing import acceptance_bucket

EXPLAINS = frozenset({"pre_open", "intraday", "post_close"})

SUPPORTS_REFUSED = "refused"
SUPPORTS_BLOCKING = "blocking"
SUPPORTS_BOTH = "both"
SUPPORTS_NEITHER = "neither"
NO_ACCEPTANCE = "no_acceptance"


def support(symbol: str, acceptance: datetime | None, refused_date: date, blocking_date: date) -> str:
    """Which date the 8-K acceptance time supports."""
    if acceptance is None:
        return NO_ACCEPTANCE
    r = acceptance_bucket(symbol, acceptance, refused_date) in EXPLAINS
    b = acceptance_bucket(symbol, acceptance, blocking_date) in EXPLAINS
    if r and b:
        return SUPPORTS_BOTH
    if r:
        return SUPPORTS_REFUSED
    if b:
        return SUPPORTS_BLOCKING
    return SUPPORTS_NEITHER


def describe(verdict: str) -> str:
    return {
        SUPPORTS_REFUSED: "SEC acceptance supports the refused date",
        SUPPORTS_BLOCKING: "SEC acceptance supports the blocking row",
        SUPPORTS_BOTH: "SEC acceptance is consistent with both dates",
        SUPPORTS_NEITHER: "SEC acceptance explains neither date",
        NO_ACCEPTANCE: "no SEC acceptance time stored for the blocking row",
    }[verdict]


async def blocking_row_acceptance(session: AsyncSession, ticker_id: uuid.UUID, blocking_date: date) -> datetime | None:
    """The acceptance time stored with the blocking row's report timing, if any."""
    return await session.scalar(text("""
        SELECT acceptance_datetime FROM earnings_report_timing
        WHERE ticker_id = :t AND event_date = :d
    """), {"t": ticker_id, "d": blocking_date})
