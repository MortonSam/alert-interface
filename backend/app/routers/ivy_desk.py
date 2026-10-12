"""Ivy v3's pricing desk, behind IVY_DESK_V3 (the admin token sees it while the flag is off, as the other flags work). The verdict
ledger lives in routers/ivy_verdicts.py, whose only gate is the picks ledger's (test_reviewer_key keeps the two apart)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.config import settings
from app.database import get_db
from app.schemas.pricing_desk import PricingCardRead
from app.services.pricing_desk import REPORT_WINDOW_DAYS

router = APIRouter(prefix="/ivy", tags=["ivy"])


def desk_visible(admin: bool) -> bool:
    return bool(settings.ivy_desk_v3_enabled or admin)


async def stored_cards(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("SELECT value FROM system_metadata WHERE key LIKE 'pricing_card:%'"))).scalars().all()
    out = []
    for raw in rows:
        try:
            out.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    return out


@router.get("/desk-v3", response_model=list[PricingCardRead])
async def desk_v3(db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> list[PricingCardRead]:
    """Every stored card for a report within REPORT_WINDOW_DAYS, soonest report first; empty while the flag is off for everyone but the admin."""
    if not desk_visible(admin):
        return []
    today = date.today()
    horizon = today + timedelta(days=REPORT_WINDOW_DAYS)
    cards = [c for c in await stored_cards(db) if today.isoformat() <= c.get("report_date", "") <= horizon.isoformat()]
    return [PricingCardRead.model_validate(c) for c in sorted(cards, key=lambda c: (c["report_date"], c["symbol"]))]
