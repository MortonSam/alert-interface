"""The New York session for a day, from the NYSE calendar (services/trading_calendar: holidays, announced closures, 1 p.m. early
closes). The ticker page reads it through GET /system/market-session and compares its own clock with the window, so the words
"Market closed" follow the exchange's calendar rather than a fixed weekday window.

    session_for(day) -> {date, is_trading_day, half_day, reason, open_at, close_at}   open_at/close_at ISO with the New York offset
    market_session(now) -> today's session (in New York) and the next one that opens after `now`
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.trading_calendar import SPECIAL_CLOSURES, is_half_day, is_trading_day

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
HALF_DAY_CLOSE = time(13, 0)
NEXT_SESSION_SEARCH_DAYS = 14        # no NYSE closure runs longer than this

# why a day has no session, or how its session runs
REASONS = ("regular", "half_day", "weekend", "holiday", "special_closure")


def session_for(day: date) -> dict:
    """Pure: the day's session window, or why it has none."""
    if not is_trading_day(day):
        reason = "weekend" if day.weekday() >= 5 else ("special_closure" if day in SPECIAL_CLOSURES else "holiday")
        return {"date": day.isoformat(), "is_trading_day": False, "half_day": False, "reason": reason, "open_at": None, "close_at": None}
    half = is_half_day(day)
    close = HALF_DAY_CLOSE if half else CLOSE
    return {"date": day.isoformat(), "is_trading_day": True, "half_day": half, "reason": "half_day" if half else "regular",
            "open_at": datetime.combine(day, OPEN, NY).isoformat(), "close_at": datetime.combine(day, close, NY).isoformat()}


def market_session(now: datetime | None = None) -> dict:
    """Today's New York session, whether `now` falls inside it, and the next session to open after `now`."""
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    today = session_for(now.date())
    is_open = bool(today["is_trading_day"]) and datetime.fromisoformat(today["open_at"]) <= now < datetime.fromisoformat(today["close_at"])
    nxt = None
    for i in range(0, NEXT_SESSION_SEARCH_DAYS + 1):
        s = session_for(now.date() + timedelta(days=i))
        if s["is_trading_day"] and datetime.fromisoformat(s["open_at"]) > now:
            nxt = s
            break
    return {"as_of": now.isoformat(), "is_open": is_open, "today": today, "next": nxt}
