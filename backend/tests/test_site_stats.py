"""The homepage counters: four stored counts, each dated by the newest row it rests on; nothing typed."""
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.mark.asyncio
async def test_site_stats_carries_the_four_counts_and_their_dates():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/v1/system/stats")).json()
    for n, d in (("active_stocks_covered", "active_stocks_as_of"), ("earnings_reports_measured", "earnings_reports_as_of"),
                 ("fomc_reactions_measured", "fomc_reactions_as_of"), ("analyst_reactions_measured", "analyst_reactions_as_of")):
        assert isinstance(body[n], int) and body[n] >= 0
        assert body[d] is None or DATE.match(body[d]), (d, body[d])
        if body[n] == 0:
            assert body[d] is None                     # no rows, no date
    assert body["analyst_reactions_measured"] <= body["analyst_actions"]      # a measured action is a stored action
