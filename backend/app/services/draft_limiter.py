"""Per-IP and global daily rate limits for anonymous draft usage."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_metadata_service import get_value, set_value

logger = logging.getLogger(__name__)

PER_IP_LIMIT = 5
GLOBAL_DAILY_LIMIT = 150


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def check_draft_limit(
    db: AsyncSession, caller_id: str, client_ip: str
) -> None:
    if caller_id == "admin-local":
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # ── Per-IP limit ──────────────────────────────────────────────────────────
    ip_key = f"draft_rate:ip:{client_ip}"
    raw = await get_value(db, ip_key)
    timestamps: list[str] = json.loads(raw) if raw else []
    recent = [ts for ts in timestamps if datetime.fromisoformat(ts) > cutoff]
    if len(recent) >= PER_IP_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="You've used today's 5 free drafts. Come back tomorrow, or browse the research notes meanwhile.",
        )

    # ── Global daily limit ────────────────────────────────────────────────────
    today_key = f"draft_rate:global:{now.strftime('%Y-%m-%d')}"
    global_raw = await get_value(db, today_key)
    global_count = int(global_raw) if global_raw else 0
    if global_count >= GLOBAL_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Drafting is busy today and paused until tomorrow. Browse the research notes meanwhile.",
        )


async def record_draft(
    db: AsyncSession, caller_id: str, client_ip: str, symbol: str
) -> None:
    if caller_id == "admin-local":
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # ── Per-IP: append and prune ──────────────────────────────────────────────
    ip_key = f"draft_rate:ip:{client_ip}"
    raw = await get_value(db, ip_key)
    timestamps: list[str] = json.loads(raw) if raw else []
    recent = [ts for ts in timestamps if datetime.fromisoformat(ts) > cutoff]
    recent.append(now.isoformat())
    await set_value(db, ip_key, json.dumps(recent))

    # ── Global: increment ─────────────────────────────────────────────────────
    today_key = f"draft_rate:global:{now.strftime('%Y-%m-%d')}"
    global_raw = await get_value(db, today_key)
    global_count = int(global_raw) if global_raw else 0
    await set_value(db, today_key, str(global_count + 1))

    await db.commit()

    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:12]
    logger.info("draft symbol=%s ip=%s", symbol, ip_hash)
