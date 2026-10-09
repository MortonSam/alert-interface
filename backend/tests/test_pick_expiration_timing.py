"""The expected move's expiry follows report timing (chain_store.pick_expiration): an expiry on the report day counts only for
a before-open report, so EOG (after the close on Nov 6) gets Nov 13, never the Nov 6 pre-earnings leg."""
import pytest

from app.services import chain_store

EOG = ["2026-10-16", "2026-10-23", "2026-10-30", "2026-11-06", "2026-11-13", "2026-11-20"]


@pytest.mark.asyncio
@pytest.mark.parametrize("timing,want", [("amc", "2026-11-13"), (None, "2026-11-13"), ("bmo", "2026-11-06")])
async def test_an_earnings_date_takes_the_first_expiry_that_captures_the_report(monkeypatch, timing, want):
    async def exps(db, sym, source=None):
        return EOG
    async def on(db, sym, day):
        return timing if day == "2026-11-06" else chain_store._NO_REPORT
    monkeypatch.setattr(chain_store, "get_ingested_expirations", exps)
    monkeypatch.setattr(chain_store, "report_timing_on", on)
    assert await chain_store.pick_expiration(None, "EOG", "2026-11-06") == want


@pytest.mark.asyncio
async def test_a_date_with_no_report_keeps_on_or_after(monkeypatch):
    async def exps(db, sym, source=None):
        return EOG
    async def on(db, sym, day):
        return chain_store._NO_REPORT
    monkeypatch.setattr(chain_store, "get_ingested_expirations", exps)
    monkeypatch.setattr(chain_store, "report_timing_on", on)
    assert await chain_store.pick_expiration(None, "EOG", "2026-11-06") == "2026-11-06"


@pytest.mark.asyncio
async def test_report_timing_is_read_from_the_stored_event():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        got = await chain_store.report_timing_on(db, "NO-SUCH-TICKER", "2026-11-06")
        assert got is chain_store._NO_REPORT
        assert await chain_store.report_timing_on(db, "EOG", "not a date") is chain_store._NO_REPORT


def test_every_page_picks_through_the_shared_picker():
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "routers" / "tickers.py").read_text()
    assert "e >= min_exp]" not in src                     # the options bundle (the ticker page's panel) once chose inline
    assert "chosen_exp: str | None = await chain_store.pick_expiration(db, sym, min_exp)" in src
