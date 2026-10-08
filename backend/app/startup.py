"""FastAPI lifespan: check reference-data staleness on startup and trigger
a background refresh if the data is older than REFRESH_IF_OLDER_THAN_HOURS.

Design notes
------------
- The pipeline (app/scripts/refresh.py) uses subprocess.run() internally, which
  blocks.  We push it to a thread-pool executor so the event loop — and every
  API endpoint — is never blocked while the refresh runs.

- Two-layer guard against double-starts:
    1. Process-level boolean (_refresh_in_progress): prevents a second task being
       created within the same process (handles normal re-entry in tests / edge cases).
    2. DB-level sentinel (refresh_in_progress_since in system_metadata): persists
       across process restarts so that uvicorn --reload (which spawns a *new*
       process on each file-change) does not stack concurrent refreshes.  The
       sentinel is written *before* the task is scheduled and cleared in the
       task's finally block.  A sentinel older than REFRESH_SENTINEL_MAX_MINUTES
       is treated as stale (process was killed mid-run) and ignored.

- last_refreshed_at is only written by the pipeline on full success, so an
  interrupted or failed run leaves the old timestamp intact.  The badge will
  keep showing the true staleness.

- print() is used for key messages instead of logger.info() so they always
  appear in Docker / uvicorn logs regardless of logging configuration.
"""
from __future__ import annotations

import asyncio
import functools
import sys
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.nightly_clock import LAST_NIGHTLY_SLOT_KEY, NIGHTLY_CLOCK, NIGHTLY_LOCAL_TIME, latest_slot, nightly_due, slot_key
from app.services.system_metadata_service import get_value, set_value

# ── Configuration ──────────────────────────────────────────────────────────────

# Trigger a background refresh if reference data is older than this many hours.
REFRESH_IF_OLDER_THAN_HOURS = 24

# Treat the in-progress sentinel as stale after this many minutes.
# If a refresh takes longer than this or the process was killed, the next
# startup will be allowed to start a new one.
REFRESH_SENTINEL_MAX_MINUTES = 45

_KEY_LAST_REFRESHED = "last_refreshed_at"
_KEY_IN_PROGRESS    = "refresh_in_progress_since"

# ── Process-level guard ────────────────────────────────────────────────────────

# True while a background refresh task is in flight in THIS process.
_refresh_in_progress: bool = False

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    """Print to stdout (always visible in Docker logs) and also emit to logger."""
    print(f"[startup-refresh] {msg}", flush=True)
    logger.info("[startup-refresh] %s", msg)


async def _read_sentinel() -> tuple[str | None, str | None]:
    """Return (last_refreshed_at_raw, in_progress_since_raw) from system_metadata."""
    async with AsyncSessionLocal() as session:
        last     = await get_value(session, _KEY_LAST_REFRESHED)
        sentinel = await get_value(session, _KEY_IN_PROGRESS)
    return last, sentinel


async def _write_sentinel(value: str) -> None:
    async with AsyncSessionLocal() as session:
        await set_value(session, _KEY_IN_PROGRESS, value)
        await session.commit()


# ── Background worker ──────────────────────────────────────────────────────────

async def _background_refresh(nightly_slot: str | None = None) -> None:
    """Run the full refresh pipeline in a thread-pool so the event loop stays free.

    `nightly_slot` is set only by the refresh loop; a boot refresh passes None and
    so never marks a nightly slot as done.
    """
    global _refresh_in_progress
    try:
        # Local import so the scripts package is not pulled in at module load time.
        from app.scripts import refresh as pipeline  # noqa: PLC0415

        _log("Pipeline starting in background thread …")
        loop = asyncio.get_event_loop()
        exit_code: int = await loop.run_in_executor(None, functools.partial(pipeline.main, slot=nightly_slot))
        # The runner itself writes last_refreshed_at, and only when every data step exited 0 (refresh.should_record_refresh).
        # The slot is marked done here: it ran to completion, whatever the exit code; a resumed run completes the same slot.
        try:
            async with AsyncSessionLocal() as session:
                if nightly_slot:
                    await set_value(session, LAST_NIGHTLY_SLOT_KEY, nightly_slot)
                await session.commit()
        except Exception:
            pass
        if exit_code == 0:
            _log("Pipeline completed successfully.")
        else:
            _log(f"Pipeline exited with code {exit_code} (some steps failed); see /health failed_steps and step_outcomes.")
    except Exception as exc:
        _log(f"Pipeline raised an unexpected exception: {exc}.  Old data and timestamp preserved.")
        logger.exception("[startup-refresh] Exception detail:")
    finally:
        # Clear DB sentinel so future startups don't think a refresh is in progress.
        try:
            await _write_sentinel("done")
        except Exception:
            pass
        _refresh_in_progress = False


# ── Refresh loop ──────────────────────────────────────────────────────────────

LOOP_INTERVAL_SECONDS = 5 * 60   # how often the loop looks at the clock; the run starts within this of the slot


def nightly_refresh_due(now: datetime, last_slot_done: str | None, last_refreshed_raw: str | None) -> bool:
    """The nightly is due when the latest clock slot has not been run by the loop.

    `last_refreshed_raw` is accepted and ignored on purpose: a boot refresh that
    finished at 14:51Z refreshes the data but never satisfies that night's slot.
    """
    del last_refreshed_raw
    return nightly_due(now, last_slot_done)


async def _read_last_slot() -> str | None:
    async with AsyncSessionLocal() as session:
        return await get_value(session, LAST_NIGHTLY_SLOT_KEY)


async def _refresh_loop() -> None:
    """Permanent background loop: every LOOP_INTERVAL_SECONDS, start the nightly if its slot is due."""
    while True:
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
        try:
            now = datetime.now(timezone.utc)
            last_raw, sentinel_raw = await _read_sentinel()
            last_slot = await _read_last_slot()
            if not nightly_refresh_due(now, last_slot, last_raw):
                continue

            if sentinel_raw and sentinel_raw != "done":
                try:
                    started_at = datetime.fromisoformat(sentinel_raw)
                    if (now - started_at).total_seconds() / 60 < REFRESH_SENTINEL_MAX_MINUTES:
                        continue
                except ValueError:
                    pass

            global _refresh_in_progress
            if _refresh_in_progress:
                continue

            slot = slot_key(latest_slot(now))
            _log(f"Refresh loop: nightly slot {slot} ({NIGHTLY_LOCAL_TIME.strftime('%H:%M')} {NIGHTLY_CLOCK}) is due — starting or resuming refresh.")
            _refresh_in_progress = True
            await _write_sentinel(now.isoformat())
            asyncio.create_task(_background_refresh(nightly_slot=slot))

        except Exception as exc:
            _log(f"Refresh loop iteration failed ({exc}) — will retry next cycle.")



NEWS_INTERVAL_MINUTES = 60          # the intraday news run: hourly through the US session
NEWS_HOURS = (9, 17)                # New York hours the intraday run may start in, weekdays


def news_run_due(now_ny: datetime, last_run: datetime | None) -> bool:
    """Pure: an intraday news run is due on a weekday between NEWS_HOURS (New York) when the last one started an interval ago or more."""
    if now_ny.weekday() >= 5 or not (NEWS_HOURS[0] <= now_ny.hour < NEWS_HOURS[1]):
        return False
    return last_run is None or (now_ny - last_run).total_seconds() >= NEWS_INTERVAL_MINUTES * 60


async def _news_loop() -> None:
    """Hourly through the US session: refresh_news in its own process (its own Finnhub pacing, below the site's)."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    last: datetime | None = None
    while True:
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
        try:
            now = datetime.now(ny)
            if not news_run_due(now, last) or _refresh_in_progress:
                continue
            last = now
            _log("News loop: starting the intraday news run.")
            proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.scripts.refresh_news",
                                                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            _log(f"News loop: intraday news run exited {proc.returncode}.")
        except Exception as exc:
            _log(f"News loop iteration failed ({exc}); will retry next cycle.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Check staleness on startup; fire one background refresh if needed.
    Start a permanent loop that starts the nightly at its clock slot."""
    global _refresh_in_progress

    if not settings.refresh_enabled:
        _log("REFRESH_ENABLED=false — skipping startup check and refresh loop.")
        yield
        return

    # ── Stale-flag recovery ──────────────────────────────────────────────────
    # On a fresh start the process flag is always False, but the DB sentinel
    # may be left over from a previous process that died mid-run.  Clear it
    # up front so the staleness check below starts from a clean state.
    try:
        _, old_sentinel = await _read_sentinel()
        if old_sentinel and old_sentinel != "done":
            try:
                started_at = datetime.fromisoformat(old_sentinel)
                age_minutes = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
                if age_minutes >= REFRESH_SENTINEL_MAX_MINUTES:
                    _log(
                        f"Clearing stale DB sentinel ({age_minutes:.0f}m old) "
                        "from a previous process that never finished."
                    )
                    await _write_sentinel("done")
            except ValueError:
                await _write_sentinel("done")
        _refresh_in_progress = False
    except Exception as exc:
        _log(f"Stale-flag recovery failed ({exc}) — continuing.")

    # ── Startup staleness check ───────────────────────────────────────────────
    try:
        last_raw, sentinel_raw = await _read_sentinel()
        now = datetime.now(timezone.utc)
        skip_refresh = False

        # Layer 1: DB sentinel — did another process already start a refresh?
        if sentinel_raw and sentinel_raw != "done":
            try:
                started_at = datetime.fromisoformat(sentinel_raw)
                age_minutes = (now - started_at).total_seconds() / 60
                if age_minutes < REFRESH_SENTINEL_MAX_MINUTES:
                    _log(
                        f"Another process started a refresh {age_minutes:.0f}m ago "
                        f"(threshold: {REFRESH_SENTINEL_MAX_MINUTES}m) — skipping."
                    )
                    skip_refresh = True
                else:
                    _log(
                        f"Stale sentinel ({age_minutes:.0f}m old, threshold {REFRESH_SENTINEL_MAX_MINUTES}m) "
                        "— treating as dead process and proceeding with staleness check."
                    )
            except ValueError:
                pass  # unparseable sentinel — ignore it

        # Layer 2: Process-level guard
        if not skip_refresh and _refresh_in_progress:
            _log("Refresh already in progress in this process — skipping duplicate.")
            skip_refresh = True

        # Staleness check
        if not skip_refresh:
            should_refresh = False

            if last_raw is None:
                _log("last_refreshed_at not found — reference data has never been refreshed.")
                should_refresh = True
            else:
                try:
                    last_dt = datetime.fromisoformat(last_raw)
                    age_hours = (now - last_dt).total_seconds() / 3600
                    if age_hours > REFRESH_IF_OLDER_THAN_HOURS:
                        _log(
                            f"Reference data is {age_hours:.1f}h old "
                            f"(threshold: {REFRESH_IF_OLDER_THAN_HOURS}h) — scheduling background refresh."
                        )
                        should_refresh = True
                    else:
                        _log(f"Reference data is {age_hours:.1f}h old — fresh enough, skipping refresh.")
                except ValueError:
                    _log(f"Cannot parse last_refreshed_at={last_raw!r} — scheduling refresh as precaution.")
                    should_refresh = True

            if should_refresh:
                _refresh_in_progress = True
                # Write sentinel BEFORE scheduling the task so the next --reload
                # process that starts within REFRESH_SENTINEL_MAX_MINUTES will see
                # it and skip.
                await _write_sentinel(now.isoformat())
                asyncio.create_task(_background_refresh())

    except Exception as exc:
        _log(f"Startup staleness check failed ({exc}) — app will start normally without a refresh.")
        logger.exception("[startup-refresh] Exception detail:")

    # ── Start the permanent refresh loop, then yield (app serves requests) ────
    loop_task = asyncio.create_task(_refresh_loop())
    news_task = asyncio.create_task(_news_loop())
    try:
        yield
    finally:
        for task in (loop_task, news_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
