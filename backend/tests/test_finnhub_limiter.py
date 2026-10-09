"""One Finnhub budget across processes (services/finnhub_limiter) and the visitor quote that never waits
(finnhub_client.get_quote with services/quote_fallback)."""
import asyncio
import re
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services import finnhub_client as F
from app.services import finnhub_limiter as L
from app.services import quote_fallback as Q

pytestmark = pytest.mark.xdist_group(name="finnhub_calls")
NY = ZoneInfo("America/New_York")


def test_wait_seconds_holds_the_last_part_of_each_minute_for_visitors():
    assert L.wait_seconds([], L.BACKGROUND_LIMIT) == 0.0
    ages = [50.0 - i for i in range(L.BACKGROUND_LIMIT)]                     # a job's limit used, the oldest 50 s ago
    assert L.wait_seconds(ages, L.BACKGROUND_LIMIT) == pytest.approx(10.01)    # the job waits for the oldest to leave
    assert L.wait_seconds(ages, L.VISITOR_LIMIT) == 0.0                        # a visitor goes now
    assert L.wait_seconds(ages + [70.0, 61.0], L.BACKGROUND_LIMIT) == pytest.approx(10.01)   # older than the window: ignored
    assert L.BACKGROUND_LIMIT < L.VISITOR_LIMIT <= 60


TEST_TABLE = "finnhub_calls_limiter_test"     # its own table: filling the real one would slow other workers' visitor quotes


async def _seed_calls(n: int, priority: str) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(text(f"CREATE TABLE IF NOT EXISTS {TEST_TABLE} (LIKE finnhub_calls INCLUDING ALL)"))
        await s.execute(text(f"DELETE FROM {TEST_TABLE}"))
        if n:
            await s.execute(text(f"INSERT INTO {TEST_TABLE} (priority, at) SELECT :p, clock_timestamp() - interval '30 seconds' FROM generate_series(1, :n)"),
                            {"p": priority, "n": n})
        await s.commit()


@pytest.mark.asyncio
async def test_a_job_waits_at_its_limit_while_a_visitor_still_goes_across_processes(monkeypatch):
    monkeypatch.setattr(L, "TABLE", TEST_TABLE)
    await _seed_calls(L.BACKGROUND_LIMIT, L.BACKGROUND)                         # as if other processes made these
    try:
        wait = await L.try_take(L.BACKGROUND)
        assert wait is not None and 29 < wait <= 31
        assert await L.try_take(L.VISITOR) == 0.0
        await _seed_calls(L.VISITOR_LIMIT, L.VISITOR)
        assert (await L.try_take(L.VISITOR)) > 0                                 # nobody passes the whole minute's budget
    finally:
        await _seed_calls(0, L.VISITOR)


def test_the_stored_close_is_dated_by_its_session_close_on_the_new_york_clock():
    t = Q.close_time_unix(date(2026, 10, 8))
    assert datetime.fromtimestamp(t, tz=NY) == datetime(2026, 10, 8, 16, 0, tzinfo=NY)
    assert datetime.fromtimestamp(Q.close_time_unix(date(2026, 11, 27)), tz=NY).hour == 13      # the day after Thanksgiving
    q = Q.quote_from_bars([(date(2026, 10, 7), 100.0, 99.0, 101.0, 98.0), (date(2026, 10, 8), 102.0, 100.5, 103.0, 100.0)])
    assert (q["c"], q["pc"], q["d"], q["dp"], q["basis"]) == (102.0, 100.0, 2.0, 2.0, "close")
    assert Q.quote_from_bars([])["c"] is None


@pytest.mark.asyncio
async def test_a_visitor_quote_with_no_answer_in_time_serves_the_stored_close(monkeypatch):
    async def slow(self, method, path, params=None):
        await asyncio.sleep(30)
    async def stored(symbol):
        return Q.quote_from_bars([(date(2026, 10, 7), 100.0, None, None, None), (date(2026, 10, 8), 102.0, None, None, None)])
    monkeypatch.setattr(F.FinnhubClient, "_request", slow)
    monkeypatch.setattr(Q, "stored_close_quote", stored)
    c = F.FinnhubClient(priority=F.VISITOR)
    t0 = time.perf_counter()
    q = await c.get_quote("ZBRA")
    await c.close()
    assert time.perf_counter() - t0 < F.QUOTE_WAIT_SECONDS + 0.5
    assert q["basis"] == "close" and q["c"] == 102.0 and q["t"] == Q.close_time_unix(date(2026, 10, 8))


@pytest.mark.asyncio
async def test_a_visitor_quote_that_answers_is_a_last_trade_and_a_job_never_falls_back(monkeypatch):
    async def fast(self, method, path, params=None):
        return {"c": 101.5, "t": 1791489600, "d": 1.0, "dp": 1.0, "pc": 100.5}
    monkeypatch.setattr(F.FinnhubClient, "_request", fast)
    c = F.FinnhubClient(priority=F.VISITOR)
    assert (await c.get_quote("ZBRA"))["basis"] == "last_trade"
    await c.close()
    async def failing(self, method, path, params=None):
        raise RuntimeError("down")
    monkeypatch.setattr(F.FinnhubClient, "_request", failing)
    job = F.FinnhubClient()
    with pytest.raises(RuntimeError):
        await job.get_quote("ZBRA")
    await job.close()


def test_routers_read_finnhub_as_visitors():
    for f in ("discover.py", "thesis.py", "tickers.py"):
        src = (Path(__file__).parents[1] / "app" / "routers" / f).read_text()
        assert "FinnhubClient()" not in src, f


def test_every_quote_basis_has_a_label_on_the_page():
    ts = (Path(__file__).parents[2] / "frontend" / "src" / "lib" / "freshness.ts")
    if not ts.exists():
        pytest.skip("frontend not mounted in this container")
    m = re.search(r"QUOTE_BASIS_LABELS[^=]*=\s*\{([^}]*)\}", ts.read_text())
    labels = dict(re.findall(r'(\w+):\s*"([^"]*)"', m.group(1)))
    assert labels == Q.BASIS_LABELS
