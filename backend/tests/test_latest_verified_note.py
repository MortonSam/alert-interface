"""The home page's note block renders the most recently verified note, never a sample (audit item 8)."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app

SYM = "ZZNOTE"
# an hour ahead: newer than any note the copied dev data holds (one generated today would otherwise be the latest), and fresh for the home page
VERIFIED = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
VERIFICATION = {"claims": [{"claim": "Revenue grew", "status": "supported", "evidence": "10-K"}], "summary": {"supported": 1, "unsupported": 0, "contradicted": 0}}
STRUCTURED = {"rating": "neutral", "stats": {"market_cap": 4.3e12, "eps_actual": 2.01, "eps_estimate": 1.94, "eps_beat_pct": 3.6, "beat_count": 18, "total_quarters": 20, "latest_move_1d": "+3.56%", "latest_outcome": "beat"},
              "highlights": [{"lead": "Services revenue grew", "detail": "14% year over year."}, {"lead": "Beats", "detail": "18 of 20."}, {"lead": "Third", "detail": "dropped"}]}


async def _cleanup(s):
    await s.execute(text("DELETE FROM research_notes WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
    await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
    await s.commit()


async def _note(s, status, verification, verified_at, generated_at):
    await s.execute(text("""
        INSERT INTO research_notes (id, ticker_id, generated_at, source_filings, content, model_used, input_tokens, output_tokens,
                                    verification, verified_at, structured_content, status, created_at, updated_at)
        SELECT CAST(:id AS uuid), id, :g, '[]', 'text', 'm', 1, 1, CAST(:v AS jsonb), :va, CAST(:sc AS jsonb), :st, now(), now() FROM tickers WHERE symbol = :s
    """), {"id": str(uuid.uuid4()), "g": generated_at, "v": json.dumps(verification) if verification else None, "va": verified_at,
           "sc": json.dumps(STRUCTURED), "st": status, "s": SYM})


@pytest.mark.asyncio
async def test_the_latest_verified_note_is_the_newest_verified_complete_one_with_its_own_figures():
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'Note Test Inc.', true, now(), now())"), {"s": SYM})
        await _note(s, "complete", VERIFICATION, VERIFIED, VERIFIED - timedelta(hours=1))
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/research-notes/latest-verified")
            assert r.status_code == 200, r.text
            body = r.json()
            assert (body["symbol"], body["company_name"], body["rating"]) == (SYM, "Note Test Inc.", "neutral")
            assert body["stats"]["eps_actual"] == 2.01 and body["stats"]["beat_count"] is None and body["stats"]["latest_move_1d"] is None   # no beat rate or past move (note_valuation)
            assert [h["lead"] for h in body["highlights"]] == ["Services revenue grew", "Beats"]
            assert body["verification_summary"] == {"supported": 1, "unsupported": 0, "contradicted": 0}
            assert body["verified_at"].startswith(VERIFIED.isoformat()[:19])

            # an unverified complete note is not "verified"; a note whose check has not run is not shown
            async with ScriptSessionLocal() as s:
                await s.execute(text("UPDATE research_notes SET verification = NULL, verified_at = NULL WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
                await s.commit()
            # the endpoint returns the newest verified note across the table: this ticker no longer qualifies
            r = await c.get("/api/v1/research-notes/latest-verified")
            assert r.status_code in (200, 404)
            if r.status_code == 200:
                assert r.json()["symbol"] != SYM
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


@pytest.mark.asyncio
async def test_a_note_verified_more_than_14_days_ago_is_never_the_home_page_note():
    from app.routers.research_notes import HOME_NOTE_FRESH_DAYS
    assert HOME_NOTE_FRESH_DAYS == 14
    old = datetime.now(timezone.utc) - timedelta(days=HOME_NOTE_FRESH_DAYS + 1)
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'Note Test Inc.', true, now(), now())"), {"s": SYM})
        await _note(s, "complete", VERIFICATION, old, old - timedelta(hours=1))
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/research-notes/latest-verified")
            assert r.status_code in (200, 404)
            if r.status_code == 200:
                assert r.json()["symbol"] != SYM
                assert datetime.fromisoformat(r.json()["verified_at"].replace("Z", "+00:00")) >= datetime.now(timezone.utc) - timedelta(days=HOME_NOTE_FRESH_DAYS)
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)
