"""The IV snapshot step must not block on one hung price fetch."""
import asyncio
import time
from datetime import date

import app.scripts.snapshot_iv as m


def test_a_hung_price_fetch_is_skipped_after_the_timeout(monkeypatch):
    monkeypatch.setattr(m, "PRICE_FETCH_TIMEOUT", 0.05)
    async def fake_chain(session, symbol, today): return ({"calls": [], "puts": []}, "2026-10-16")
    monkeypatch.setattr(m, "_get_ingested_chain", fake_chain)
    monkeypatch.setattr(m, "_get_current_price", lambda sym: time.sleep(5))

    async def go():
        t0 = time.monotonic()
        row = await m._snapshot_one("HUNG", date(2026, 9, 22))
        return row, time.monotonic() - t0
    row, took = asyncio.run(go())
    assert "exceeded" in row["skipped"] and row["atm_iv"] is None
    assert took < 2


def test_budget_and_progress_are_wired():
    from pathlib import Path
    src = (Path(m.__file__)).read_text()
    assert "TIME_BUDGET_SECONDS" in src and "PROGRESS_EVERY" in src
    assert "asyncio.wait_for(" in src and "PRICE_FETCH_TIMEOUT" in src
    assert m.TIME_BUDGET_SECONDS < 600      # the refresh runner kills this step at 600 s
