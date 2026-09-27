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


@pytest.mark.asyncio
async def test_context_insight_never_prints_a_zero_index_median():
    """The card line compares against the same index medians Discover uses, or says why it cannot."""
    sym = await _symbol_without_upcoming_earnings()
    if sym is None:
        pytest.skip("All tickers have upcoming earnings — cannot test suggestion path")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ctx = (await client.get(f"/api/v1/theses/context?symbols={sym}")).json()[sym]
    insight = ctx["insight"] or ""
    assert "0.0% across the S&P" not in insight and "versus 0% across" not in insight, insight


def test_insight_states_why_the_index_comparison_is_absent():
    from app.routers.discover import (
        INDEX_BASE_NOT_LOADED, INDEX_BASE_TOO_FEW, INDEX_BASE_ZERO, _suggestion_insight,
    )
    cond = {"total": 12, "beat_count": 9, "bbd_count": 1, "miss_count": 3, "avg_abs_1d": 4.2,
            "avg_1d_on_beat": None, "avg_1d_on_miss": None}

    line, gen, z = _suggestion_insight(cond, None, None, None)
    assert "0.0%" not in line and "versus 0%" not in line
    assert INDEX_BASE_NOT_LOADED in line and z == 0.0

    too_few = {"beat_rate": {"med": None, "sd": 1.0}, "avg_abs_move": {"med": None, "sd": 1.0}}
    line, _, _ = _suggestion_insight(cond, None, None, too_few)
    assert INDEX_BASE_TOO_FEW in line and "0.0%" not in line

    zero = {"beat_rate": {"med": 0.0, "sd": 1.0}, "avg_abs_move": {"med": 0.0, "sd": 1.0}}
    line, _, _ = _suggestion_insight(cond, None, None, zero)
    assert INDEX_BASE_ZERO in line and "0.0%" not in line

    base = {"beat_rate": {"med": 0.7, "sd": 0.15}, "avg_abs_move": {"med": 3.5, "sd": 5.0}}
    line, gen, z = _suggestion_insight(cond, None, None, base)
    assert gen == "beat_rate" and "versus 70% across the S&P" in line
    assert abs(z - abs(0.75 - 0.7) / 0.15) < 1e-9

    line, gen, _ = _suggestion_insight(dict(cond, beat_count=0), None, None, base)
    assert gen == "avg_move" and "versus \u00b13.5% across the S&P" in line
