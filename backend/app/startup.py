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
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI

from app.database import AsyncSessionLocal
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

async def _background_refresh() -> None:
    """Run the full refresh pipeline in a thread-pool so the event loop stays free."""
    global _refresh_in_progress
    try:
        # Local import so the scripts package is not pulled in at module load time.
        from app.scripts import refresh as pipeline  # noqa: PLC0415

        _log("Pipeline starting in background thread …")
        loop = asyncio.get_event_loop()
        exit_code: int = await loop.run_in_executor(None, pipeline.main)

        if exit_code == 0:
            # Write last_refreshed_at here — refresh.py's own asyncio.run()
            # write fails when called via run_in_executor (nested loop).
            try:
                now_iso = datetime.now(tz=timezone.utc).isoformat()
                async with AsyncSessionLocal() as session:
                    await set_value(session, _KEY_LAST_REFRESHED, now_iso)
                    await session.commit()
            except Exception:
                pass
            _log("Pipeline completed successfully — last_refreshed_at updated.")
        else:
            _log(
                f"Pipeline exited with code {exit_code}.  "
                "Old timestamp preserved; badge will show true staleness."
            )
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


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Check staleness and in-progress sentinel on startup; fire one background refresh if needed."""
    global _refresh_in_progress

    try:
        last_raw, sentinel_raw = await _read_sentinel()
        now = datetime.now(timezone.utc)

        # ── Layer 1: DB sentinel — did another process already start a refresh? ──
        if sentinel_raw and sentinel_raw != "done":
            try:
                started_at = datetime.fromisoformat(sentinel_raw)
                age_minutes = (now - started_at).total_seconds() / 60
                if age_minutes < REFRESH_SENTINEL_MAX_MINUTES:
                    _log(
                        f"Another process started a refresh {age_minutes:.0f}m ago "
                        f"(threshold: {REFRESH_SENTINEL_MAX_MINUTES}m) — skipping."
                    )
                    yield
                    return
                else:
                    _log(
                        f"Stale sentinel ({age_minutes:.0f}m old, threshold {REFRESH_SENTINEL_MAX_MINUTES}m) "
                        "— treating as dead process and proceeding with staleness check."
                    )
            except ValueError:
                pass  # unparseable sentinel — ignore it

        # ── Layer 2: Process-level guard ────────────────────────────────────────
        if _refresh_in_progress:
            _log("Refresh already in progress in this process — skipping duplicate.")
            yield
            return

        # ── Staleness check ─────────────────────────────────────────────────────
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
            # Write sentinel BEFORE scheduling the task so the next --reload process
            # that starts within REFRESH_SENTINEL_MAX_MINUTES will see it and skip.
            await _write_sentinel(now.isoformat())
            asyncio.create_task(_background_refresh())

    except Exception as exc:
        _log(f"Startup staleness check failed ({exc}) — app will start normally without a refresh.")
        logger.exception("[startup-refresh] Exception detail:")

    yield  # ← app is live and serving requests from this point onward
