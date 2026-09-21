"""Admin-only endpoints — chain ingestion, diagnostics."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.credit_shadow_pick import CreditShadowPick
from app.models.shadow_pick import ShadowPick
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
    # Track the nearest expiration per symbol for put/call ratio
    nearest_chain: dict[str, ChainIngestItem] = {}
    today_str = date.today().isoformat()
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
            # Track nearest future expiration per symbol for put/call
            if item.expiration >= today_str:
                prev = nearest_chain.get(sym)
                if prev is None or item.expiration < prev.expiration:
                    nearest_chain[sym] = item
        except Exception as exc:
            errors.append(f"{sym}: {exc}")

    # Compute and store put/call ratio from the nearest expiration per symbol
    MIN_TOTAL_CONTRACTS = 50
    pc_stored = 0
    for sym, item in nearest_chain.items():
        put_vol = sum((p.get("volume") or 0) for p in item.puts)
        call_vol = sum((c.get("volume") or 0) for c in item.calls)
        total = put_vol + call_vol
        if total < MIN_TOTAL_CONTRACTS or call_vol == 0:
            ratio = None
        else:
            ratio = round(put_vol / call_vol, 4)
        snapshot_date = (
            date.fromisoformat(item.chain_last_trade[:10])
            if item.chain_last_trade
            else date.today()
        )
        await db.execute(text("""
            INSERT INTO put_call_snapshots
                (id, symbol, snapshot_date, ratio, basis, put_total, call_total,
                 expiration_used, computation_version, created_at)
            VALUES
                (gen_random_uuid(), :symbol, :snapshot_date, :ratio, 'volume',
                 :put_total, :call_total, :expiration_used, 1, :now)
            ON CONFLICT (symbol, snapshot_date) DO UPDATE SET
                ratio = :ratio,
                put_total = :put_total,
                call_total = :call_total,
                expiration_used = :expiration_used,
                created_at = :now
        """), {
            "symbol": sym,
            "snapshot_date": snapshot_date,
            "ratio": ratio,
            "put_total": put_vol,
            "call_total": call_vol,
            "expiration_used": item.expiration,
            "now": datetime.now(timezone.utc),
        })
        pc_stored += 1

    await db.commit()
    result: dict = {"ingested": len(ingested), "symbols": ingested, "put_call_stored": pc_stored}
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


@router.get("/shadow-summary", dependencies=[Depends(require_admin)])
async def shadow_summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Shadow model summary: settled stats, hit rates, last 20 rows."""
    # Settled rows (have actual_5d)
    settled_rows = (await db.execute(
        select(ShadowPick).where(ShadowPick.actual_5d.is_not(None))
    )).scalars().all()

    settled_count = len(settled_rows)

    # Shadow hit rate: among settled rows where would_pick=True
    shadow_picks = [r for r in settled_rows if r.would_pick]
    shadow_hits = sum(1 for r in shadow_picks if float(r.actual_5d) > 0)
    shadow_hit_rate = shadow_hits / len(shadow_picks) if shadow_picks else None

    # v2 hit rate: among settled rows where v2_decision='picked'
    v2_picks = [r for r in settled_rows if r.v2_decision == "picked"]
    v2_hits = sum(1 for r in v2_picks if float(r.actual_5d) > 0)
    v2_hit_rate = v2_hits / len(v2_picks) if v2_picks else None

    # Last 20 rows
    recent = (await db.execute(
        select(ShadowPick)
        .order_by(ShadowPick.decided_at.desc())
        .limit(20)
    )).scalars().all()

    recent_out = []
    for r in recent:
        recent_out.append({
            "symbol": r.symbol,
            "event_date": r.event_date.isoformat(),
            "probability": float(r.probability),
            "would_pick": r.would_pick,
            "v2_decision": r.v2_decision,
            "actual_5d": float(r.actual_5d) if r.actual_5d is not None else None,
            "top_factors": r.top_factors,
        })

    return {
        "settled": settled_count,
        "shadow_picks": len(shadow_picks),
        "shadow_hits": shadow_hits,
        "shadow_hit_rate": shadow_hit_rate,
        "v2_picks": len(v2_picks),
        "v2_hits": v2_hits,
        "v2_hit_rate": v2_hit_rate,
        "recent": recent_out,
    }


@router.get("/credit-shadow-summary", dependencies=[Depends(require_admin)])
async def credit_shadow_summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Credit shadow iron condor summary: settled stats, win rate, last 20 rows."""
    total = (await db.execute(
        select(func.count()).select_from(CreditShadowPick)
    )).scalar_one()

    settled_rows = (await db.execute(
        select(CreditShadowPick).where(CreditShadowPick.settled_at.is_not(None))
    )).scalars().all()

    settled_count = len(settled_rows)
    wins = sum(1 for r in settled_rows if r.pnl_dollars is not None and float(r.pnl_dollars) > 0)
    win_rate = wins / settled_count if settled_count else None
    mean_pnl_dollars = (
        sum(float(r.pnl_dollars) for r in settled_rows if r.pnl_dollars is not None) / settled_count
        if settled_count else None
    )
    mean_pnl_pct = (
        sum(float(r.pnl_pct) for r in settled_rows if r.pnl_pct is not None) / settled_count
        if settled_count else None
    )
    worst_loss = (
        min(float(r.pnl_dollars) for r in settled_rows if r.pnl_dollars is not None)
        if settled_count else None
    )

    recent = (await db.execute(
        select(CreditShadowPick)
        .order_by(CreditShadowPick.decided_at.desc())
        .limit(20)
    )).scalars().all()

    recent_out = []
    for r in recent:
        recent_out.append({
            "symbol": r.symbol,
            "event_date": r.event_date.isoformat(),
            "spot": float(r.spot),
            "credit_received": float(r.credit_received),
            "max_loss": float(r.max_loss),
            "pnl_dollars": float(r.pnl_dollars) if r.pnl_dollars is not None else None,
            "pnl_pct": float(r.pnl_pct) if r.pnl_pct is not None else None,
            "settled": r.settled_at is not None,
        })

    return {
        "total": total,
        "settled": settled_count,
        "wins": wins,
        "win_rate": win_rate,
        "mean_pnl_dollars": mean_pnl_dollars,
        "mean_pnl_pct": mean_pnl_pct,
        "worst_loss": worst_loss,
        "recent": recent_out,
    }
