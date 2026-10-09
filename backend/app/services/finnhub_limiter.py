"""One Finnhub request budget for every process: the site, the nightly's subprocesses and the news run.

Finnhub allows 60 requests a minute per key, counted across every process that holds it. Each process used to pace only
itself (the site at 55 a minute, the news run at 40), so together they ran past 60 and visitors' quotes sat in 429
backoff for about 55 seconds. Now every request is logged in Postgres (finnhub_calls), and a request goes only when fewer
than its limit were made in the trailing minute by all processes together: VISITOR_LIMIT for a visitor's read,
BACKGROUND_LIMIT for a job. Jobs therefore always leave VISITOR_LIMIT - BACKGROUND_LIMIT requests a minute that only
visitors can use. The check runs under a transaction-scoped advisory lock, so two processes never take the same slot.
If the database cannot be reached the request is paced by the in-process window alone, and the fault is logged once.
"""
from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

VISITOR, BACKGROUND = "visitor", "background"
VISITOR_LIMIT = 58          # every request in the trailing minute, all processes; two short of Finnhub's 60 for clock skew
BACKGROUND_LIMIT = 45       # a job waits once this many were made; the rest of the minute is held for visitors
WINDOW_SECONDS = 60.0
LOCK_KEY = 0x46484E42       # "FHNB"
TABLE = "finnhub_calls"     # a test points this at its own table so filling it never slows another test's quotes

log = logging.getLogger("finnhub_limiter")
_engines: dict[int, AsyncEngine] = {}
_db_fault_logged = False


def limit_for(priority: str) -> int:
    return VISITOR_LIMIT if priority == VISITOR else BACKGROUND_LIMIT


def wait_seconds(ages: list[float], limit: int) -> float:
    """Pure: seconds until one more request fits under `limit`, given the ages (seconds ago) of the requests in the window.
    0 when it fits now."""
    recent = sorted((a for a in ages if a < WINDOW_SECONDS), reverse=True)        # oldest first
    if len(recent) < limit:
        return 0.0
    # the request fits once all but limit - 1 of them have left the window
    return max(0.05, WINDOW_SECONDS - recent[len(recent) - limit] + 0.01)


def _engine() -> AsyncEngine:
    """A small engine per event loop (asyncpg connections belong to the loop that opened them)."""
    loop_id = id(asyncio.get_running_loop())
    eng = _engines.get(loop_id)
    if eng is None:
        eng = create_async_engine(settings.database_url, pool_size=2, max_overflow=4, pool_pre_ping=True,
                                  connect_args={"server_settings": {"statement_timeout": "3000"}})
        _engines[loop_id] = eng
    return eng


async def try_take(priority: str) -> float | None:
    """Take a slot if one is free: 0.0 when taken, else the seconds to wait. None when the database could not be used."""
    global _db_fault_logged
    try:
        async with _engine().begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
            ages = (await conn.execute(text(
                f"SELECT extract(epoch FROM clock_timestamp() - at) FROM {TABLE} WHERE at > clock_timestamp() - interval '60 seconds'"
            ))).scalars().all()
            wait = wait_seconds([float(a) for a in ages], limit_for(priority))
            if wait == 0.0:
                await conn.execute(text(f"INSERT INTO {TABLE} (priority) VALUES (:p)"), {"p": priority})
                if random.random() < 0.02:
                    await conn.execute(text(f"DELETE FROM {TABLE} WHERE at < clock_timestamp() - interval '10 minutes'"))
            return wait
    except Exception as exc:
        if not _db_fault_logged:
            log.warning("Finnhub shared budget unavailable, pacing this process alone: %s", type(exc).__name__)
            _db_fault_logged = True
        return None


async def acquire(priority: str) -> bool:
    """Wait for a slot in the shared budget. False when the database could not be used (the caller paces locally)."""
    while True:
        wait = await try_take(priority)
        if wait is None:
            return False
        if wait == 0.0:
            return True
        await asyncio.sleep(min(wait, 5.0))
