"""check_pnl_pct_units runs against the real schema (it once selected theses.symbol, a column that does not exist)."""
import asyncio

import pytest

from app.database import ScriptSessionLocal
from app.scripts.validate_data import ERROR, check_pnl_pct_units


def _run(coro):
    return asyncio.run(coro)


def test_pnl_pct_units_executes_against_the_real_schema():
    async def go():
        async with ScriptSessionLocal() as session:
            return await check_pnl_pct_units(session)
    try:
        result = _run(go())
    except Exception as exc:  # no database in this environment
        pytest.skip(f"database unavailable: {exc}")
    assert not result.message.startswith("Check raised"), result.message
    assert result.name == "pnl_pct_units"
    assert result.level != ERROR or "disagree" in result.message   # an ERROR here must be a data finding, not a crash
