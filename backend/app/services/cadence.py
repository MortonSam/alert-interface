"""The one cadence record every page renders its "nightly", "once a day" and price-source wording from.

Nothing here is typed in copy: the nightly slot is NIGHTLY_LOCAL_TIME on the New York clock (services/nightly_clock),
the options cadence is the courier's declared schedule (one capture a day at COURIER_CAPTURE_LOCAL New York), and the
quote record names the source and how each quote is dated. Finnhub publishes no fetchable statement of a delay for US
quotes (its documentation and pricing pages render in the browser only; checked QUOTE_DELAY_CHECKED), so no delay figure
is claimed: every quote carries its own last-trade time and the pages show it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services import chain_store
from app.services.nightly_clock import NIGHTLY_CLOCK, slot_local_label, slot_utc_today

MARKET_CLOCK = "America/New_York"
COURIER_CAPTURE_LOCAL = "16:05"          # the courier's launchd schedule on Sam's Mac, weekdays, New York clock (CLAUDE.md)
OPTIONS_CAPTURES_PER_DAY = 1
NIGHTLY_RUNS_PER_DAY = 1
QUOTE_SOURCE = "Finnhub"
QUOTE_DELAY_STATEMENT: str | None = None  # Finnhub states none in a document we can fetch; see the module docstring
QUOTE_DELAY_CHECKED = "2026-10-05"
QUOTE_DATED_BY = "each quote's own last-trade time"


def nightly_local_time(now_utc: datetime | None = None) -> str:
    """The nightly slot on the New York clock (services/nightly_clock); the same every day of the year."""
    del now_utc
    return slot_local_label()


def cadence(now_utc: datetime | None = None) -> dict:
    return {
        "nightly": {"per_day": NIGHTLY_RUNS_PER_DAY, "local_time": nightly_local_time(now_utc), "clock": NIGHTLY_CLOCK, "utc_today": slot_utc_today(now_utc)},
        "options": {"per_day": OPTIONS_CAPTURES_PER_DAY, "captured_local": COURIER_CAPTURE_LOCAL, "clock": MARKET_CLOCK,
                    "fresh_sessions": chain_store.CHAIN_FRESH_TRADING_DAYS},
        "quotes": {"source": QUOTE_SOURCE, "delay_statement": QUOTE_DELAY_STATEMENT, "delay_checked": QUOTE_DELAY_CHECKED, "dated_by": QUOTE_DATED_BY},
    }
