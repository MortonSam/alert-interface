from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.cadence import cadence
from app.services.system_metadata_service import get_value

router = APIRouter(prefix="/system", tags=["system"])


class SystemStatus(BaseModel):
    last_refreshed_at: datetime | None          # written only when every data step of the nightly exited 0
    total_tickers: int
    total_reactions: int
    most_recent_reaction_date: date | None
    datasets: dict = {}                         # per dataset: at, ok, failed, steps (services/dataset_freshness)
    cadence: dict | None = None                 # services/cadence: what "nightly" and "once a day" mean


@router.get("/status", response_model=SystemStatus)
async def get_system_status(db: AsyncSession = Depends(get_db)) -> SystemStatus:
    last_refreshed_raw = await get_value(db, "last_refreshed_at")
    last_refreshed_at: datetime | None = None
    if last_refreshed_raw:
        try:
            last_refreshed_at = datetime.fromisoformat(last_refreshed_raw)
        except ValueError:
            pass

    total_tickers = await db.scalar(
        select(func.count()).select_from(Ticker).where(Ticker.is_active.is_(True))
    ) or 0

    total_reactions = await db.scalar(
        select(func.count()).select_from(HistoricalReaction)
    ) or 0

    most_recent_reaction_date: date | None = await db.scalar(
        select(func.max(HistoricalReaction.event_date))
    )

    datasets: dict = {}
    try:
        import json as _json
        from app.models.system_metadata import SystemMetadata
        from app.services.dataset_freshness import dataset_ages
        raw = await get_value(db, "step_outcomes")
        rows = (await db.execute(select(SystemMetadata.key, SystemMetadata.value).where(SystemMetadata.key.like("step:%")))).all()
        stamps = {k.replace("step:", "").replace(":last_success", ""): v for k, v in rows}
        datasets = dataset_ages(_json.loads(raw) if raw else {}, stamps)
    except Exception:
        datasets = {}

    return SystemStatus(
        last_refreshed_at=last_refreshed_at,
        total_tickers=total_tickers,
        total_reactions=total_reactions,
        most_recent_reaction_date=most_recent_reaction_date,
        datasets=datasets,
        cadence=cadence(),
    )


_CONTRACTS_CACHE: dict = {"at": None, "value": None}
CONTRACTS_CACHE_SECONDS = 900          # the latest night's chain count changes once a day; counting it scans every stored chain
CONTRACTS_SOURCE = "courier chains"    # the chains the pages read; the Intrinio shadow chains are stored under another prefix


async def latest_night_contracts(db: AsyncSession) -> tuple[int, str | None]:
    """(contracts across the latest night's stored courier chains, that night's chain date). Counted from the stored
    chain JSON by text (one "strike" per contract), dated by each chain's own chain_last_trade."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    now = datetime.now(timezone.utc)
    if _CONTRACTS_CACHE["at"] and (now - _CONTRACTS_CACHE["at"]).total_seconds() < CONTRACTS_CACHE_SECONDS:
        return _CONTRACTS_CACHE["value"]
    row = (await db.execute(text("""
        WITH c AS (
            SELECT substring(value from '"chain_last_trade": ?"([0-9]{4}-[0-9]{2}-[0-9]{2})') AS d,
                   (length(value) - length(replace(value, '"strike"', ''))) / length('"strike"') AS n
            FROM system_metadata WHERE key LIKE 'chain:%' AND key NOT LIKE 'chain:%:%:%')
        SELECT d, sum(n) FROM c WHERE d IS NOT NULL AND d = (SELECT max(d) FROM c) GROUP BY d"""))).first()
    value = (int(row[1] or 0), row[0]) if row else (0, None)
    _CONTRACTS_CACHE.update(at=now, value=value)
    return value


@router.get("/stats")
async def get_site_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """The homepage counters: four live counts from stored tables, each with the date of the newest row it rests on.
    Nothing here is typed by hand. "Measured" means a stored reaction row with a one-day move."""
    from sqlalchemy import text
    from app.services.price_history_exclusion import EXCLUDED_SYMBOLS_SQL

    async def measured(event_type: str) -> tuple[int, str | None]:
        row = (await db.execute(text(
            "SELECT count(*), max(hr.event_date) FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id "
            f"WHERE hr.event_type = '{event_type}' AND hr.pct_change_1d IS NOT NULL AND t.symbol NOT IN " + EXCLUDED_SYMBOLS_SQL
        ))).one()
        return int(row[0] or 0), row[1].isoformat() if row[1] else None

    contracts, contracts_as_of = await latest_night_contracts(db)
    prices = (await db.execute(text("SELECT count(*), max(date) FROM price_bars_shadow"))).one()
    earnings_n, earnings_as_of = await measured("earnings")
    analyst_n, analyst_as_of = await measured("analyst_action")
    return {
        "option_contracts_captured": contracts,
        "option_contracts_as_of": contracts_as_of,
        "option_contracts_source": CONTRACTS_SOURCE,
        "licensed_daily_prices": int(prices[0] or 0),
        "licensed_daily_prices_as_of": prices[1].isoformat() if prices[1] else None,
        "earnings_reports_measured": earnings_n,
        "earnings_reports_as_of": earnings_as_of,
        "analyst_reactions_measured": analyst_n,
        "analyst_reactions_as_of": analyst_as_of,
    }
