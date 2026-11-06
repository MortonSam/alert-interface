"""Hypothetical trade results (services/trade_results): every saved idea with an option leg whose expiration has passed is scored
once from the stored official close on its expiration day. Nightly step "Hypothetical trade results"; it writes only the result
column of saved ideas.

    python -m app.scripts.score_trades
"""
from __future__ import annotations

import asyncio
import sys

from app.database import ScriptSessionLocal

STEP_LABEL = "Hypothetical trade results"


async def run() -> int:
    from app.services.step_outcomes import record_step_fields
    from app.services.trade_results import score_due
    async with ScriptSessionLocal() as db:
        out = await score_due(db)
    await record_step_fields(STEP_LABEL, out)
    print(f"{STEP_LABEL}: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
