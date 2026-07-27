"""Admin-only endpoints — chain ingestion, diagnostics."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.services.system_metadata_service import set_value

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_CHAINS_PER_REQUEST = 50
MAX_CONTRACTS_PER_SIDE = 300


class ChainIngestItem(BaseModel):
    symbol: str
    expiration: str
    calls: list[dict]
    puts: list[dict]
    chain_last_trade: str | None = None


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
    for item in payload.chains:
        sym = item.symbol.upper()
        if len(item.calls) > MAX_CONTRACTS_PER_SIDE or len(item.puts) > MAX_CONTRACTS_PER_SIDE:
            raise HTTPException(
                status_code=422,
                detail=f"{sym}: too many contracts ({len(item.calls)} calls / {len(item.puts)} puts); max {MAX_CONTRACTS_PER_SIDE} per side.",
            )
        chain_dict = {
            "calls": item.calls,
            "puts": item.puts,
            "expiration": item.expiration,
            "chain_last_trade": item.chain_last_trade,
        }
        key = f"chain:{sym}:{item.expiration}"
        await set_value(db, key, json.dumps(chain_dict))
        ingested.append(sym)

    await db.commit()
    return {"ingested": len(ingested), "symbols": ingested}
