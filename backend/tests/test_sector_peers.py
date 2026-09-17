"""
Consistency tests: sector peer endpoints read from stored snapshot rows.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.main import app
from app.models.sector_peer_snapshot import SectorPeerSnapshot


@pytest.mark.asyncio
async def test_sector_peers_matches_summary():
    """sector_avg_abs_1d and peer_count from /sector-peers must equal /summary."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sym = "AAPL"

        summary_resp = await client.get(f"/api/v1/reactions/summary?symbol={sym}")
        if summary_resp.status_code == 404:
            pytest.skip(f"{sym} not in database")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()

        peers_resp = await client.get(f"/api/v1/reactions/sector-peers?symbol={sym}")
        assert peers_resp.status_code == 200
        peers = peers_resp.json()

        assert peers["sector_avg_abs_1d"] == summary["sector_avg_abs_1d"]
        assert peers["peer_count"] == summary["sector_peer_count"]


@pytest.mark.asyncio
async def test_sector_peers_equals_stored_snapshot():
    """Endpoint values must come from the stored SectorPeerSnapshot row."""
    sym = "AAPL"

    # Read the latest stored snapshot for this symbol
    async with AsyncSessionLocal() as session:
        snap = (await session.execute(
            select(SectorPeerSnapshot)
            .where(SectorPeerSnapshot.symbol == sym)
            .order_by(SectorPeerSnapshot.as_of_date.desc())
            .limit(1)
        )).scalar_one_or_none()

    if snap is None:
        pytest.skip(f"No sector_peer_snapshot for {sym}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/reactions/summary?symbol={sym}")
        assert resp.status_code == 200
        data = resp.json()

    stored_avg = round(float(snap.sector_avg_abs_1d), 2) if snap.sector_avg_abs_1d is not None else None
    assert data["sector_avg_abs_1d"] == stored_avg
    assert data["sector_peer_count"] == snap.sector_peer_count
    assert data["sector_as_of"] == snap.as_of_date.isoformat()
