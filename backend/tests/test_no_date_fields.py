"""A ticker with no future earnings date still tells the page when the calendar was last asked."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app

SYM = "ZZNODATE"
CHECKED = datetime(2026, 9, 29, 6, 5, tzinfo=timezone.utc)


async def _cleanup(s):
    await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
    await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
    await s.commit()


@pytest.mark.asyncio
async def test_by_symbol_and_list_carry_checked_at_without_a_date():
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await s.execute(text("""INSERT INTO tickers (id, symbol, name, is_active, earnings_checked_at, created_at, updated_at)
                                VALUES (gen_random_uuid(), :s, 'no date test', true, :c, now(), now())"""), {"s": SYM, "c": CHECKED})
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            one = (await c.get(f"/api/v1/tickers/by-symbol/{SYM}")).json()
            many = {t["symbol"]: t for t in (await c.get("/api/v1/tickers?active_only=true")).json()}
        for t in (one, many[SYM]):
            assert t["next_earnings_date"] is None and t["next_earnings_source"] is None
            assert t["next_earnings_checked_at"].startswith("2026-09-29T06:05")
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


def test_discover_cards_and_the_draft_fact_block_carry_the_fields():
    from pathlib import Path
    from app.routers.discover import SuggestionItem, UnusuallyActiveItem
    for model in (SuggestionItem, UnusuallyActiveItem):
        fields = model.model_fields
        assert "earnings_checked_at" in fields and "earnings_source" in fields, model.__name__
    # the draft's fact_block is an untyped dict: the router must put the fields in it
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    assert '"earnings_source":           data.get("earnings_source")' in src
    assert '"earnings_checked_at":       data.get("earnings_checked_at")' in src
