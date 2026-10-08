"""Stored revenue and EPS growth (services/growth), behind GROWTH_ENABLED; the admin token sees it while the flag is off. Only figures
two readers agreed on are stored, so only those are served."""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.database import get_db

router = APIRouter(prefix="/tickers", tags=["growth"])


class GrowthRow(BaseModel):
    metric: str
    period_end: date
    year_ago_end: date | None
    value: float | None
    year_ago_value: float | None
    growth_pct: float | None      # null when the phrase is words (a swing between a loss and a profit, from zero) or the comparison is held
    phrase: str | None
    held_reason: str | None
    readers: str | None


class GrowthResponse(BaseModel):
    enabled: bool
    rows: list[GrowthRow] = []


@router.get("/{symbol}/growth", response_model=GrowthResponse)
async def ticker_growth(symbol: str, db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> GrowthResponse:
    from app.config import settings
    if not (settings.growth_enabled or admin):
        return GrowthResponse(enabled=False)
    rows = (await db.execute(sa.text("""
        SELECT metric, period_end, year_ago_end, value, year_ago_value, growth_pct, phrase, held_reason, readers FROM growth_figures
        WHERE symbol = :s ORDER BY metric, period_end DESC"""), {"s": symbol.upper()})).all()
    return GrowthResponse(enabled=True, rows=[GrowthRow(
        metric=r[0], period_end=r[1], year_ago_end=r[2], value=float(r[3]) if r[3] is not None else None,
        year_ago_value=float(r[4]) if r[4] is not None else None, growth_pct=float(r[5]) if r[5] is not None else None,
        phrase=r[6], held_reason=r[7], readers=r[8]) for r in rows])
