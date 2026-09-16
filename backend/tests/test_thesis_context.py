"""
Regression test for thesis_context endpoint.

The _suggestion_insight() path (no upcoming earnings) previously crashed with
TypeError due to missing positional arguments.  This test calls /theses/context
with a symbol that has no earnings in the next 30 days and verifies it returns
200 with the expected shape.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.main import app
from app.models.ticker import Ticker


async def _symbol_without_upcoming_earnings() -> str | None:
    """Find an active ticker with no earnings event in the next 30 days."""
    async with AsyncSessionLocal() as session:
        row = await session.execute(text("""
            SELECT t.symbol
            FROM tickers t
            WHERE t.is_active = true
              AND NOT EXISTS (
                  SELECT 1 FROM events e
                  WHERE e.ticker_id = t.id
                    AND e.event_type = 'earnings'
                    AND e.event_date >= CURRENT_DATE
                    AND e.event_date <= CURRENT_DATE + 30
              )
            LIMIT 1
        """))
        r = row.scalar_one_or_none()
        return r


@pytest.mark.asyncio
async def test_thesis_context_no_upcoming_earnings():
    """Endpoint must return 200 for tickers without imminent earnings (suggestion path)."""
    sym = await _symbol_without_upcoming_earnings()
    if sym is None:
        pytest.skip("All tickers have upcoming earnings — cannot test suggestion path")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/theses/context?symbols={sym}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert sym in data
        ctx = data[sym]
        # No upcoming earnings → earnings_proximity should be null
        assert ctx["earnings_proximity"] is None
        # insight should be str or None (not a tuple, not an error)
        assert ctx["insight"] is None or isinstance(ctx["insight"], str)
