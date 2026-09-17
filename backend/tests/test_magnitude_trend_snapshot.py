"""
Consistency tests: conditional endpoint reads magnitude trend from stored snapshot rows.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.main import app
from app.models.magnitude_trend_snapshot import MagnitudeTrendSnapshot


@pytest.mark.asyncio
async def test_magnitude_trend_matches_stored_snapshot():
    """Endpoint values must come from the stored MagnitudeTrendSnapshot row."""
    sym = "AAPL"

    # Read the latest stored snapshot for this symbol
    async with AsyncSessionLocal() as session:
        snap = (await session.execute(
            select(MagnitudeTrendSnapshot)
            .where(MagnitudeTrendSnapshot.symbol == sym)
            .order_by(MagnitudeTrendSnapshot.as_of_date.desc())
            .limit(1)
        )).scalar_one_or_none()

    if snap is None:
        pytest.skip(f"No magnitude_trend_snapshot for {sym}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/reactions/conditional?symbol={sym}")
        assert resp.status_code == 200
        data = resp.json()

    stored_recent = round(float(snap.recent_avg_abs_1d), 2) if snap.recent_avg_abs_1d is not None else None
    stored_prior = round(float(snap.prior_avg_abs_1d), 2) if snap.prior_avg_abs_1d is not None else None

    assert data["recent_avg_abs_1d"] == stored_recent
    assert data["prior_avg_abs_1d"] == stored_prior
    assert data["magnitude_trend"] == snap.trend
