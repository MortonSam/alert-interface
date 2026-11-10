"""One site-wide daily cap on AI spend across every model call (research notes, Build a Trade drafts, Ask Ivy, the readers).

Settings AI_DAILY_SPEND_CAP_USD (default 20.0). The day is the New York calendar day, so the cap resets at midnight ET. Every model
call is counted here as it returns, in one place (AnthropicClient._create, `record_call`): its estimated cost (services/research_cost;
an unpriced model adds nothing and is counted apart) goes to the day's total, to its pool and to its feature. A visitor feature asks
`cap_reached` before it runs; when the cap is reached it shows its existing closed message until midnight ET. The per-feature counts
and caps (draft_limiter policies, ASK_IVY_DAILY_CAP_USD) stay in force underneath this one.

Two pools (Sam, 2026-11-02, after the night's notes spent $23.81 of a $15 day and Build a Trade closed for the day): a call made while
serving a visitor's request is the visitor pool (main.py sets it per request); every other call, the nightly's steps, scripts and
background loops, is the nightly pool. A nightly call runs only when the day's total spend plus the most that call can cost
(`call_ceiling_usd`) leaves visitors at least VISITOR_RESERVE_USD of the cap, at any time of day; otherwise it raises
NightlyBudgetReached before the request is sent.
"""
from __future__ import annotations

import contextvars
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.services.system_metadata_service import get_value, set_value

SPEND_KEY = "ai_spend"              # system_metadata "ai_spend:{YYYY-MM-DD}" (New York day) holds the day's estimated spend in USD
UNPRICED_KEY = "ai_spend_unpriced"  # "ai_spend_unpriced:{day}" counts model calls with no price in the table
POOL_KEY = "ai_spend_pool"          # "ai_spend_pool:{day}:{pool}": the day's spend by pool
FEATURE_KEY = "ai_spend_feature"    # "ai_spend_feature:{day}:{pool}:{feature}": the day's spend by pool and feature
CALLS_KEY = "ai_spend_calls"        # "ai_spend_calls:{day}:{pool}:{feature}": the day's model calls by pool and feature
CLOCK = ZoneInfo("America/New_York")

VISITOR, NIGHTLY = "visitor", "nightly"
_POOL: contextvars.ContextVar[str] = contextvars.ContextVar("ai_spend_pool", default=NIGHTLY)


class NightlyBudgetReached(RuntimeError):
    """A nightly-pool model call refused before it was sent: it could leave visitors less than their reserve of today's cap."""


def pool() -> str:
    """The pool the current call counts against: VISITOR inside a request (main.py), NIGHTLY everywhere else."""
    return _POOL.get()


def set_pool(name: str):
    """Set the pool for this context; returns the token to reset it with."""
    return _POOL.set(name)


def spend_day(now: datetime | None = None) -> str:
    """The New York calendar day the cap applies to."""
    return (now or datetime.now(timezone.utc)).astimezone(CLOCK).strftime("%Y-%m-%d")


def cap_usd() -> float:
    return float(settings.ai_daily_spend_cap_usd)


# The nightly's share of the cap (Sam, 2026-11-02, with the cap at $15): research notes at most NOTES_NIGHT_USD a night, the
# walkthroughs at most WALKTHROUGHS_NIGHT_USD until every stock has one, and visitors always keep at least VISITOR_RESERVE_USD of
# the day's cap. (Until 2026-11-02: a $35 cap, notes $30, or $16 with walkthroughs at $14, visitors $5.)
NOTES_NIGHT_USD = 6.0
NOTES_WITH_WALKTHROUGHS_USD = 6.0
WALKTHROUGHS_NIGHT_USD = 5.0
VISITOR_RESERVE_USD = 4.0
VISITOR_RESERVE_SHARE = 0.5          # under a small cap visitors keep half of it (Sam, 2026-11-10: $3 a day until the plan's credit, Nov 19)
WALKTHROUGH_STEP = "Ivy walkthroughs"


# Until the plan's monthly credit arrives (Sam, 2026-11-10: $20 of credit, a $3 daily cap, until about Nov 19) the nightly spends on
# notes alone: no note is written for a material 8-K alone or checked again (scripts/generate_notes), and the release reader reads
# with its pattern parser only (scripts/seed_release_eps; nothing new is stored, since both readers must agree).
SAVER_UNTIL = date(2026, 11, 19)


def saver_on(today: date) -> bool:
    return today < SAVER_UNTIL


def visitor_reserve(cap: float) -> float:
    """Pure: what visitors always keep of the day's cap: VISITOR_RESERVE_USD, or half of a cap too small to leave the nightly anything
    above that ($1.50 of a $3 cap)."""
    return min(VISITOR_RESERVE_USD, cap * VISITOR_RESERVE_SHARE)


def notes_night_budget(cap: float, walkthroughs_live: bool) -> float:
    """Pure: what tonight's research notes may spend: their share, never past what leaves the walkthroughs theirs (when they run)
    and visitors VISITOR_RESERVE_USD."""
    share = NOTES_WITH_WALKTHROUGHS_USD if walkthroughs_live else NOTES_NIGHT_USD
    return max(0.0, min(share, cap - visitor_reserve(cap) - (WALKTHROUGHS_NIGHT_USD if walkthroughs_live else 0.0)))


def nightly_room(cap: float, spent_total: float) -> float:
    """Pure: what nightly-pool calls may still spend today: whatever keeps visitors VISITOR_RESERVE_USD of the cap."""
    return max(0.0, cap - visitor_reserve(cap) - spent_total)


def call_ceiling_usd(model: str | None, request: dict) -> float | None:
    """Pure: the most one request can cost, before it is sent: its prompt's characters as tokens (at most one token per 3
    characters, a generous bound for English and JSON) plus its max_tokens, at the model's list prices. None: no price."""
    from app.services.research_cost import PRICES_USD_PER_MTOK
    if not model or model not in PRICES_USD_PER_MTOK:
        return None
    chars = len(json.dumps(request.get("messages") or [], default=str)) + len(json.dumps(request.get("system") or "", default=str))
    pin, pout = PRICES_USD_PER_MTOK[model]
    return round((chars / 3 * pin + int(request.get("max_tokens") or 0) * pout) / 1_000_000, 4)


def walkthroughs_live() -> bool:
    """The walkthrough nightly is one of the nightly's steps (scripts/refresh.STEPS)."""
    from app.scripts.refresh import STEPS
    return any(label == WALKTHROUGH_STEP for label, _ in STEPS)


# A dated reminder in the morning digest: from its day, while the cap is still above the value it names (Sam, 2026-10-29).
CAP_REMINDERS = ((date(2026, 11, 3), 15.0, "set AI_DAILY_SPEND_CAP_USD to $15 on Railway (Sam, 2026-11-02)"),)

# The month's spend named in the digest once it passes each line (Sam, 2026-11-02): the sum of the month's New York days so far.
MONTH_WARNINGS_USD = (150.0, 200.0)


def month_days(today: date) -> list[str]:
    """Pure: the New York days of today's month up to today, as the spend keys name them."""
    return [today.replace(day=d).isoformat() for d in range(1, today.day + 1)]


def month_warnings(spent: float, today: date) -> list[str]:
    """Pure: the digest's warning for the highest line the month's AI spend has passed, or nothing."""
    passed = [w for w in MONTH_WARNINGS_USD if spent >= w]
    if not passed:
        return []
    return [f"AI spend in {today.strftime('%B')} is ${spent:.2f}, past the ${max(passed):.0f} line"]


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
    return int(float(raw)) if raw else 0


async def cap_reached(db, now: datetime | None = None) -> bool:
    return reached(await spend_today(db, now))


async def _incr(db, key: str, amount: float) -> None:
    """Add `amount` to a stored number in one statement, so two calls finishing together both count."""
    await db.execute(text("""INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())
        ON CONFLICT (key) DO UPDATE SET value = ((COALESCE(NULLIF(system_metadata.value, ''), '0'))::numeric + (:v)::numeric)::text,
        updated_at = now()"""), {"k": key, "v": f"{amount:.5f}"})


async def check_nightly(db, model: str | None, request: dict, now: datetime | None = None) -> None:
    """Before a nightly-pool call: raise NightlyBudgetReached when its ceiling would cut into the visitors' reserve. A visitor
    call passes (its feature checks `cap_reached` itself); so does an unpriced model's call, which is counted apart."""
    if pool() != NIGHTLY:
        return
    from app.services import ai_pause
    pause = await ai_pause.paused(db)
    if pause:                                     # the key check found no credit: nothing is sent tonight (services/ai_pause)
        raise NightlyBudgetReached(f"nightly AI call refused: AI paused since {ai_pause.since_words(pause)} ({pause.get('kind')})")
    ceiling = call_ceiling_usd(model, request)
    if ceiling is None:
        return
    room = nightly_room(cap_usd(), await spend_today(db, now))
    if ceiling > room:
        raise NightlyBudgetReached(f"nightly AI call refused: it could cost ${ceiling:.2f} and only ${room:.2f} of today's "
                                   f"${cap_usd():.2f} cap is left before visitors' ${visitor_reserve(cap_usd()):.2f}")


async def record_call(db, feature: str, cost: float | None, now: datetime | None = None) -> None:
    """Every model call, as it returns (AnthropicClient._create): its cost to the day, its pool and its feature, and one call
    counted, committed on `db` (a session of its own)."""
    day, p = spend_day(now), pool()
    await _incr(db, f"{CALLS_KEY}:{day}:{p}:{feature}", 1)
    if cost is None:
        await _incr(db, f"{UNPRICED_KEY}:{day}", 1)
    elif cost > 0:
        await _incr(db, f"{SPEND_KEY}:{day}", cost)
        await _incr(db, f"{POOL_KEY}:{day}:{p}", cost)
        await _incr(db, f"{FEATURE_KEY}:{day}:{p}:{feature}", cost)
    await db.commit()


async def breakdown(db, day: str) -> dict:
    """The day's spend and calls by pool and feature: {pool: {feature: {"usd": x, "calls": n}}}."""
    rows = (await db.execute(text("SELECT key, value FROM system_metadata WHERE key LIKE :a OR key LIKE :b"),
                             {"a": f"{FEATURE_KEY}:{day}:%", "b": f"{CALLS_KEY}:{day}:%"})).all()
    out: dict = {}
    for key, value in rows:
        kind, _day, p, feature = key.split(":", 3)
        slot = out.setdefault(p, {}).setdefault(feature, {"usd": 0.0, "calls": 0})
        if kind == FEATURE_KEY:
            slot["usd"] = round(float(value), 4)
        else:
            slot["calls"] = int(float(value))
    return out


async def summary(db, now: datetime | None = None) -> dict:
    spent = await spend_today(db, now)
    by_pool = {p: round(float(await get_value(db, f"{POOL_KEY}:{spend_day(now)}:{p}") or 0), 4) for p in (VISITOR, NIGHTLY)}
    return {"day": spend_day(now), "clock": "America/New_York", "spent_usd": round(spent, 4), "cap_usd": cap_usd(), "reached": reached(spent),
            "unpriced_calls": await unpriced_today(db, now), "by_pool": by_pool, "visitor_reserve_usd": visitor_reserve(cap_usd()),
            "nightly_room_usd": round(nightly_room(cap_usd(), spent), 4)}
