"""The homepage counters: four live counts from stored tables, each dated by the newest row it rests on; nothing typed."""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COUNTS = (("option_contracts_captured", "option_contracts_as_of"), ("licensed_daily_prices", "licensed_daily_prices_as_of"),
          ("earnings_reports_measured", "earnings_reports_as_of"), ("analyst_reactions_measured", "analyst_reactions_as_of"))


@pytest.mark.asyncio
async def test_site_stats_carries_the_four_counts_their_dates_and_the_chain_source():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/system/stats")).json()
    assert set(body) == {k for pair in COUNTS for k in pair} | {"option_contracts_source"}
    for n, d in COUNTS:
        assert isinstance(body[n], int) and body[n] >= 0
        assert body[d] is None or DATE.match(body[d]), (d, body[d])
        if body[n] == 0:
            assert body[d] is None                     # no rows, no date
    assert body["option_contracts_source"] == "courier chains"
