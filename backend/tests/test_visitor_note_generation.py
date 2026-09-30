"""A visitor generates a research note only where none exists; replacing one is the owner's (audit item 13)."""
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import app.auth as auth
import app.routers.research_notes as rn
from app.main import app

TOKEN = "test-admin-token"


class _Note:
    def __init__(self, status):
        self.status = status
        self.verification = None
        self.error = None


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", TOKEN)
    monkeypatch.setattr(rn, "public_generation_enabled", lambda: True)

    async def resolve(db, ticker_id, symbol):
        class T: id = "tid"; symbol = "AAPL"
        return T()

    async def no_generation(*a, **k):
        raise HTTPException(status_code=419, detail="generation path")   # reached the generating branch

    monkeypatch.setattr(rn, "_resolve_ticker", resolve)
    monkeypatch.setattr(rn, "check_limit", no_generation)
    monkeypatch.setattr(rn, "start_research_note_generation", no_generation)
    monkeypatch.setattr(rn, "record_use", no_generation)

    def reader(note, admin):
        raise HTTPException(status_code=418, detail=f"existing:{note.status}:{admin}")   # reached the existing-note return
    monkeypatch.setattr(rn, "note_for_reader", reader)
    return monkeypatch


@pytest.mark.asyncio
async def test_a_visitor_gets_the_existing_note_back_whatever_its_state_and_nothing_is_generated(wired):
    for status in ("complete", "generating", "verifying"):
        async def existing(db, ticker_id, symbol, _s=status):
            return _Note(_s)
        wired.setattr(rn, "get_research_note", existing)
        wired.setattr(rn, "verification_failed", lambda n: False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/research-notes/generate?force=true", json={"symbol": "AAPL"})
        assert r.status_code == 418 and r.json()["detail"] == f"existing:{status}:False", status   # force is not a visitor's
    # a failed generation produced no note: the visitor may try again (the generating branch is reached)
    async def failed(db, ticker_id, symbol):
        return _Note("failed")
    wired.setattr(rn, "get_research_note", failed)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": "AAPL"})
    assert r.status_code == 419


@pytest.mark.asyncio
async def test_an_unverified_note_tells_the_visitor_the_owner_regenerates_it(wired):
    async def existing(db, ticker_id, symbol):
        return _Note("verification_failed")
    wired.setattr(rn, "get_research_note", existing)
    wired.setattr(rn, "verification_failed", lambda n: True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": "AAPL"})
    assert r.status_code == 409 and r.json()["detail"] == rn.NOTE_UNPUBLISHED_MESSAGE


@pytest.mark.asyncio
async def test_the_policy_says_who_may_regenerate(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", TOKEN)
    monkeypatch.setattr(rn, "public_generation_enabled", lambda: True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        anon = (await c.get("/api/v1/research-notes/policy")).json()
        admin = (await c.get("/api/v1/research-notes/policy", headers={"X-Admin-Token": TOKEN})).json()
    assert anon["can_generate"] is True and anon["can_regenerate"] is False
    assert admin["can_generate"] is True and admin["can_regenerate"] is True
    src = rn.__file__
    text = open(src).read()
    assert text.index('if existing is not None and existing.status != "failed" and not admin:') < text.index("await check_limit(")
