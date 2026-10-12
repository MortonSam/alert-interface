"""Ivy v3's verdict ledger: public once LEDGER_PUBLIC is on, else the admin token and reviewer keys, exactly as the picks ledger
(may_read_ledger; never is_admin here, test_reviewer_key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import may_read_ledger
from app.constants import LEDGER_PUBLIC, LEDGER_START
from app.database import get_db
from app.models.pricing_verdict import PricingVerdict
from app.schemas.pricing_desk import PricingVerdictRead

router = APIRouter(prefix="/ivy", tags=["ivy"])


def _f(v):
    return float(v) if v is not None else None


@router.get("/verdicts", response_model=list[PricingVerdictRead])
async def verdicts(db: AsyncSession = Depends(get_db), ledger_reader: bool = Depends(may_read_ledger)) -> list[PricingVerdictRead]:
    """The verdict ledger since LEDGER_START, newest report first: public once LEDGER_PUBLIC is on, else the admin token and reviewer keys."""
    if not LEDGER_PUBLIC and not ledger_reader:
        return []
    rows = (await db.execute(select(PricingVerdict).where(PricingVerdict.report_date >= LEDGER_START).order_by(PricingVerdict.report_date.desc(), PricingVerdict.symbol))).scalars().all()
    return [PricingVerdictRead(symbol=r.symbol, report_date=r.report_date.isoformat(), computed_at=r.computed_at.isoformat(), computation_version=r.computation_version,
                               verdict=r.verdict, verdict_structure=r.verdict_structure, ev_long_call=_f(r.ev_long_call), ev_long_straddle=_f(r.ev_long_straddle),
                               ev_bull_call_spread=_f(r.ev_bull_call_spread), ev_iron_condor=_f(r.ev_iron_condor), settled_at=r.settled_at.isoformat() if r.settled_at else None,
                               actual_move_pct=_f(r.actual_move_pct), settled_long_call=_f(r.settled_long_call), settled_long_straddle=_f(r.settled_long_straddle),
                               settled_bull_call_spread=_f(r.settled_bull_call_spread), settled_iron_condor=_f(r.settled_iron_condor)) for r in rows]
