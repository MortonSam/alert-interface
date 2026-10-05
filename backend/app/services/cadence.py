"""The one cadence record every page renders its "nightly", "once a day" and price-source wording from.

Nothing here is typed in copy: the nightly slot is NIGHTLY_RUN_UTC_HOUR shown on the New York clock for today's date,
the options cadence is the courier's declared schedule (one capture a day at COURIER_CAPTURE_LOCAL New York), and the
quote record names the source and how each quote is dated. Finnhub publishes no fetchable statement of a delay for US
quotes (its documentation and pricing pages render in the browser only; checked QUOTE_DELAY_CHECKED), so no delay figure
is claimed: every quote carries its own last-trade time and the pages show it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services import chain_store
from app.services.nightly_clock import NIGHTLY_RUN_UTC_HOUR

MARKET_CLOCK = "America/New_York"
COURIER_CAPTURE_LOCAL = "16:05"          # the courier's launchd schedule on Sam's Mac, weekdays, New York clock (CLAUDE.md)
OPTIONS_CAPTURES_PER_DAY = 1
NIGHTLY_RUNS_PER_DAY = 1
QUOTE_SOURCE = "Finnhub"
QUOTE_DELAY_STATEMENT: str | None = None  # Finnhub states none in a document we can fetch; see the module docstring
QUOTE_DELAY_CHECKED = "2026-10-05"
QUOTE_DATED_BY = "each quote's own last-trade time"


def nightly_local_time(now_utc: datetime | None = None) -> str:
    """The nightly slot as a New York wall-clock time for this date ("02:00" in summer, "01:00" in winter)."""
    now = now_utc or datetime.now(timezone.utc)
    slot = now.replace(hour=NIGHTLY_RUN_UTC_HOUR, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    return slot.astimezone(ZoneInfo(MARKET_CLOCK)).strftime("%H:%M")


def cadence(now_utc: datetime | None = None) -> dict:
    return {
        "nightly": {"per_day": NIGHTLY_RUNS_PER_DAY, "utc_hour": NIGHTLY_RUN_UTC_HOUR, "local_time": nightly_local_time(now_utc), "clock": MARKET_CLOCK},
        "options": {"per_day": OPTIONS_CAPTURES_PER_DAY, "captured_local": COURIER_CAPTURE_LOCAL, "clock": MARKET_CLOCK,
                    "fresh_sessions": chain_store.CHAIN_FRESH_TRADING_DAYS},
        "quotes": {"source": QUOTE_SOURCE, "delay_statement": QUOTE_DELAY_STATEMENT, "delay_checked": QUOTE_DELAY_CHECKED, "dated_by": QUOTE_DATED_BY},
    }
