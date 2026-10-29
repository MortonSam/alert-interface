"""One site-wide daily cap on AI spend across every visitor-triggered feature (research notes, Build a Trade drafts, Ask Ivy).

Settings AI_DAILY_SPEND_CAP_USD (default 20.0). The day is the New York calendar day, so the cap resets at midnight ET. Each feature
adds its estimated cost here after the model runs (services/research_cost; an unpriced model adds nothing and is counted apart) and
asks `cap_reached` before it runs; when the cap is reached the feature shows its existing closed message until midnight ET. The
per-feature counts and caps (draft_limiter policies, ASK_IVY_DAILY_CAP_USD) stay in force underneath this one.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.system_metadata_service import get_value, set_value

SPEND_KEY = "ai_spend"              # system_metadata "ai_spend:{YYYY-MM-DD}" (New York day) holds the day's estimated spend in USD
UNPRICED_KEY = "ai_spend_unpriced"  # "ai_spend_unpriced:{day}" counts model calls with no price in the table
CLOCK = ZoneInfo("America/New_York")


def spend_day(now: datetime | None = None) -> str:
    """The New York calendar day the cap applies to."""
    return (now or datetime.now(timezone.utc)).astimezone(CLOCK).strftime("%Y-%m-%d")


def cap_usd() -> float:
    return float(settings.ai_daily_spend_cap_usd)


# The nightly's share of the cap (Sam, 2026-10-29, with the cap raised to $35 until Nov 15): until the walkthrough nightly is live,
# research notes may use up to NOTES_NIGHT_USD; once walkthroughs run, notes get at most NOTES_WITH_WALKTHROUGHS_USD and the
# walkthroughs at most WALKTHROUGHS_NIGHT_USD; visitors always keep at least VISITOR_RESERVE_USD of the day's cap.
NOTES_NIGHT_USD = 30.0
NOTES_WITH_WALKTHROUGHS_USD = 16.0
WALKTHROUGHS_NIGHT_USD = 14.0
VISITOR_RESERVE_USD = 5.0
WALKTHROUGH_STEP = "Ivy walkthroughs"


def notes_night_budget(cap: float, walkthroughs_live: bool) -> float:
    """Pure: what tonight's research notes may spend: their share, never past what leaves the walkthroughs theirs (when they run)
    and visitors VISITOR_RESERVE_USD."""
    share = NOTES_WITH_WALKTHROUGHS_USD if walkthroughs_live else NOTES_NIGHT_USD
    return max(0.0, min(share, cap - VISITOR_RESERVE_USD - (WALKTHROUGHS_NIGHT_USD if walkthroughs_live else 0.0)))


def walkthroughs_live() -> bool:
    """The walkthrough nightly is one of the nightly's steps (scripts/refresh.STEPS)."""
    from app.scripts.refresh import STEPS
    return any(label == WALKTHROUGH_STEP for label, _ in STEPS)


# A dated reminder in the morning digest: from its day, while the cap is still above the value it names (Sam, 2026-10-29).
CAP_REMINDERS = ((date(2026, 11, 15), 20.0, "set AI_DAILY_SPEND_CAP_USD back to $20 on Railway (raised to $35 until Nov 15, 2026)"),)


def cap_reminders(today: date, cap: float) -> list[str]:
    """Pure: the reminders due on `today` with the cap at `cap`; one clears itself once the cap is back."""
    return [text_ for day, back_to, text_ in CAP_REMINDERS if today >= day and cap > back_to]


def reached(spent: float, cap: float | None = None) -> bool:
    """Pure: the cap is reached once today's spend meets it."""
    return spent >= (cap_usd() if cap is None else cap)


async def spend_today(db, now: datetime | None = None) -> float:
    raw = await get_value(db, f"{SPEND_KEY}:{spend_day(now)}")
    return float(raw) if raw else 0.0


async def unpriced_today(db, now: datetime | None = None) -> int:
    raw = await get_value(db, f"{UNPRICED_KEY}:{spend_day(now)}")
    return int(raw) if raw else 0


async def cap_reached(db, now: datetime | None = None) -> bool:
    return reached(await spend_today(db, now))


async def add(db, cost: float | None, now: datetime | None = None, commit: bool = True) -> None:
    """Add one model call's estimated cost to the day; None (an unpriced model) is counted, never estimated."""
    day = spend_day(now)
    if cost is None:
        await set_value(db, f"{UNPRICED_KEY}:{day}", str(await unpriced_today(db, now) + 1))
    elif cost > 0:
        await set_value(db, f"{SPEND_KEY}:{day}", f"{await spend_today(db, now) + cost:.5f}")
    else:
        return
    if commit:
        await db.commit()


async def summary(db, now: datetime | None = None) -> dict:
    spent = await spend_today(db, now)
    return {"day": spend_day(now), "clock": "America/New_York", "spent_usd": round(spent, 4), "cap_usd": cap_usd(), "reached": reached(spent),
            "unpriced_calls": await unpriced_today(db, now)}
