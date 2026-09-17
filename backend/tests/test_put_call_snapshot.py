"""
Consistency tests: put-call endpoint reads from stored snapshot rows.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.main import app
from app.models.put_call_snapshot import PutCallSnapshot


@pytest.mark.asyncio
async def test_put_call_matches_stored_snapshot():
    """Endpoint values must come from the stored PutCallSnapshot row."""
    sym = "AAPL"

    # Read the latest stored snapshot for this symbol
    async with AsyncSessionLocal() as session:
        snap = (await session.execute(
            select(PutCallSnapshot)
            .where(PutCallSnapshot.symbol == sym)
            .order_by(PutCallSnapshot.snapshot_date.desc())
            .limit(1)
        )).scalar_one_or_none()

    if snap is None:
        pytest.skip(f"No put_call_snapshot for {sym}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/tickers/put-call/{sym}")
        assert resp.status_code == 200
        data = resp.json()

    stored_ratio = round(float(snap.ratio), 4) if snap.ratio is not None else None
    assert data["ratio"] == stored_ratio
    assert data["snapshot_date"] == snap.snapshot_date.isoformat()
    assert data["expiration_used"] == snap.expiration_used
