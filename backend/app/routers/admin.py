"""Admin-only endpoints — chain ingestion, diagnostics."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.system_metadata import SystemMetadata
from app.services.system_metadata_service import set_value

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_CHAINS_PER_REQUEST = 50
MAX_CONTRACTS_PER_SIDE = 500


def _sanitize_floats(obj):
    """Replace NaN/Inf with None so json.dumps never produces invalid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


class ChainIngestItem(BaseModel):
    symbol: str
    expiration: str
    calls: list[dict]
    puts: list[dict]
    chain_last_trade: str | None = None
    underlying_price: float | None = None


class ChainIngestRequest(BaseModel):
    chains: list[ChainIngestItem]


@router.post("/ingest-options-chains", dependencies=[Depends(require_admin)])
async def ingest_options_chains(
    payload: ChainIngestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept pre-fetched options chains (from a residential-IP courier) and
    store them in system_metadata so the draft engine can use fresh data
    even when datacenter yfinance fetches return stale/empty chains.

    Each chain is keyed by ``chain:{SYMBOL}:{EXPIRATION}``.
    """
    if len(payload.chains) > MAX_CHAINS_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail=f"Too many chains ({len(payload.chains)}); max {MAX_CHAINS_PER_REQUEST} per request.",
        )

    ingested: list[str] = []
    errors: list[str] = []
    for item in payload.chains:
        sym = item.symbol.upper()
        if len(item.calls) > MAX_CONTRACTS_PER_SIDE or len(item.puts) > MAX_CONTRACTS_PER_SIDE:
            errors.append(f"{sym}: {len(item.calls)}c/{len(item.puts)}p exceeds {MAX_CONTRACTS_PER_SIDE}")
            continue
        try:
            chain_dict = _sanitize_floats({
                "calls": item.calls,
                "puts": item.puts,
                "expiration": item.expiration,
                "chain_last_trade": item.chain_last_trade,
                "underlying_price": item.underlying_price,
            })
            key = f"chain:{sym}:{item.expiration}"
            await set_value(db, key, json.dumps(chain_dict))
            ingested.append(sym)
        except Exception as exc:
            errors.append(f"{sym}: {exc}")

    await db.commit()
    result: dict = {"ingested": len(ingested), "symbols": ingested}
    if errors:
        result["errors"] = errors
    return result


@router.get("/chain-expirations", dependencies=[Depends(require_admin)])
async def chain_expirations(db: AsyncSession = Depends(get_db)) -> dict:
    """Return all stored chain expirations grouped by symbol.

    Response: ``{"AAPL": ["2026-10-17", "2026-11-21"], ...}``
    Used by chain_courier to discover which expirations are already priced.
    """
    rows = (await db.execute(
        select(SystemMetadata.key).where(SystemMetadata.key.like("chain:%"))
    )).scalars().all()
    out: dict[str, list[str]] = defaultdict(list)
    for key in rows:
        parts = key.split(":")
        if len(parts) == 3:
            out[parts[1]].append(parts[2])
    return {sym: sorted(exps) for sym, exps in out.items()}


@router.delete("/expired-chains", dependencies=[Depends(require_admin)])
async def delete_expired_chains(db: AsyncSession = Depends(get_db)) -> dict:
    """Delete chain keys whose expiration is in the past."""
    rows = (await db.execute(
        select(SystemMetadata.key).where(SystemMetadata.key.like("chain:%"))
    )).scalars().all()
    today_str = date.today().isoformat()
    expired_keys = []
    for key in rows:
        parts = key.split(":")
        if len(parts) == 3 and parts[2] < today_str:
            expired_keys.append(key)
    if expired_keys:
        await db.execute(
            delete(SystemMetadata).where(SystemMetadata.key.in_(expired_keys))
        )
        await db.commit()
    return {"deleted": len(expired_keys)}
