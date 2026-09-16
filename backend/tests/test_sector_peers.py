"""
Consistency test: sector-peers endpoint returns the same sector_avg_abs_1d and
peer_count as the reaction summary endpoint for the same symbol.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_sector_peers_matches_summary():
    """sector_avg_abs_1d and peer_count from /sector-peers must equal /summary."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Pick a symbol that exists — use AAPL as a safe default.
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
