"""Per-IP and site-wide daily rate limits for anonymous use of the paid endpoints.

One limiter, two policies: thesis drafts (the original) and research note
generation. Per-IP use is a list of timestamps under one system_metadata key,
so hour and day windows are read from the same record; the site-wide count is
a daily key. A use is charged when the work starts and refunded when the work
fails, so a failure never costs the visitor a slot.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_metadata_service import get_value, set_value

logger = logging.getLogger(__name__)

PER_IP_LIMIT = 5
GLOBAL_DAILY_LIMIT = 150

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class LimitPolicy:
    prefix: str                     # system_metadata key prefix, e.g. "draft_rate"
    per_ip_day: int                 # uses per client IP in a sliding 24 hours
    global_day: int                 # uses site-wide per UTC calendar day
    per_ip_hour: int | None = None  # uses per client IP in a sliding hour (None: no hourly limit)
    admin_bypasses_global: bool = True
    per_ip_hour_message: str = "{noun} is limited to {n} per hour per visitor; try again after {at}"
    per_ip_day_message: str = "{noun} is limited to {n} per day per visitor; try again after {at}"
    global_message: str = "{noun} has reached today's site-wide limit of {n}; try again tomorrow"
    noun: str = "This"


DRAFT_POLICY = LimitPolicy(
    prefix="draft_rate", per_ip_day=PER_IP_LIMIT, global_day=GLOBAL_DAILY_LIMIT,
    per_ip_day_message="You've used today's {n} free drafts. Come back tomorrow, or browse the research notes meanwhile.",
    global_message="Drafting is busy today and paused until tomorrow. Browse the research notes meanwhile.",
    noun="Drafting",
)

RESEARCH_GENERATION_POLICY = LimitPolicy(
    prefix="research_gen", per_ip_hour=5, per_ip_day=15, global_day=150,
    admin_bypasses_global=False,      # the owner skips the per-IP limits, never the site-wide cap
    noun="Note generation",
)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _ip_key(policy: LimitPolicy, ip: str) -> str:
    return f"{policy.prefix}:ip:{ip}"


def _global_key(policy: LimitPolicy, now: datetime) -> str:
    return f"{policy.prefix}:global:{now.strftime('%Y-%m-%d')}"


def _fmt_et(at: datetime) -> str:
    return at.astimezone(ET).strftime("%H:%M") + " ET"


async def _ip_uses(db: AsyncSession, policy: LimitPolicy, ip: str, now: datetime) -> list[datetime]:
    raw = await get_value(db, _ip_key(policy, ip))
    stamps = [datetime.fromisoformat(t) for t in (json.loads(raw) if raw else [])]
    return sorted(t for t in stamps if t > now - timedelta(hours=24))


async def global_count_today(db: AsyncSession, policy: LimitPolicy, now: datetime | None = None) -> int:
    raw = await get_value(db, _global_key(policy, now or datetime.now(timezone.utc)))
    return int(raw) if raw else 0


async def check_limit(db: AsyncSession, policy: LimitPolicy, caller_id: str, client_ip: str) -> None:
    """Raise 429 with a plain sentence when the caller is over any limit of the policy."""
    now = datetime.now(timezone.utc)
    admin = caller_id == "admin-local"

    if not admin:
        uses = await _ip_uses(db, policy, client_ip, now)
        if policy.per_ip_hour is not None:
            in_hour = [t for t in uses if t > now - timedelta(hours=1)]
            if len(in_hour) >= policy.per_ip_hour:
                raise HTTPException(status_code=429, detail=policy.per_ip_hour_message.format(
                    noun=policy.noun, n=policy.per_ip_hour, at=_fmt_et(in_hour[0] + timedelta(hours=1))))
        if len(uses) >= policy.per_ip_day:
            raise HTTPException(status_code=429, detail=policy.per_ip_day_message.format(
                noun=policy.noun, n=policy.per_ip_day, at=_fmt_et(uses[0] + timedelta(hours=24))))

    if admin and policy.admin_bypasses_global:
        return
    if await global_count_today(db, policy, now) >= policy.global_day:
        raise HTTPException(status_code=429, detail=policy.global_message.format(noun=policy.noun, n=policy.global_day))


async def record_use(db: AsyncSession, policy: LimitPolicy, caller_id: str, client_ip: str, label: str) -> str | None:
    """Charge one use. Returns the charge timestamp (ISO) so a failed job can refund it, or None if nothing was charged."""
    now = datetime.now(timezone.utc)
    admin = caller_id == "admin-local"
    charged = False

    if not admin:
        uses = await _ip_uses(db, policy, client_ip, now)
        uses.append(now)
        await set_value(db, _ip_key(policy, client_ip), json.dumps([t.isoformat() for t in uses]))
        charged = True

    if not (admin and policy.admin_bypasses_global):
        await set_value(db, _global_key(policy, now), str(await global_count_today(db, policy, now) + 1))
        charged = True

    await db.commit()
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:12]
    logger.info("%s use label=%s ip=%s admin=%s", policy.prefix, label, ip_hash, admin)
    return now.isoformat() if charged else None


async def refund_use(db: AsyncSession, policy: LimitPolicy, client_ip: str, charged_at: str | None) -> None:
    """Give back a charged use: the work failed, the visitor pays nothing."""
    if not charged_at:
        return
    at = datetime.fromisoformat(charged_at)
    raw = await get_value(db, _ip_key(policy, client_ip))
    stamps = json.loads(raw) if raw else []
    if charged_at in stamps:
        stamps.remove(charged_at)
        await set_value(db, _ip_key(policy, client_ip), json.dumps(stamps))
    key = _global_key(policy, at)
    raw = await get_value(db, key)
    if raw and int(raw) > 0:
        await set_value(db, key, str(int(raw) - 1))
    await db.commit()


async def check_draft_limit(db: AsyncSession, caller_id: str, client_ip: str) -> None:
    await check_limit(db, DRAFT_POLICY, caller_id, client_ip)


async def record_draft(db: AsyncSession, caller_id: str, client_ip: str, symbol: str) -> None:
    await record_use(db, DRAFT_POLICY, caller_id, client_ip, symbol)
