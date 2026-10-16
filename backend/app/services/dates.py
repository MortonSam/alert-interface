"""The site's one date format on the backend, for any sentence a visitor reads (frontend DESIGN.md, mirrored by lib/dates.fmtDate):
"Oct 23, 2026". Internal notes (validate rows, admin and cache keys, logs) keep ISO dates; app/tests/test_visitor_dates.py holds the
line between the two."""
from __future__ import annotations

import re
from datetime import date, datetime


def fmt_day(d: date | datetime | str | None) -> str | None:
    """Pure: "Oct 23, 2026" from a date, a datetime or an ISO string; None from None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    elif not isinstance(d, date):
        d = date.fromisoformat(str(d)[:10])
    return d.strftime("%b %-d, %Y")


_ISO_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def fmt_days_in(text: str | None) -> str | None:
    """Pure: a stored sentence with every ISO date in it written "Oct 23, 2026" (reasons stored before 2026-10-16 carry ISO dates)."""
    return _ISO_DAY.sub(lambda m: fmt_day(m.group(1)), text) if text else text
