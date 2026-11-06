"""The visitor share of the daily AI cap and the Build a Trade draft cache (Sam, 2026-11-02).

Nov 2: the night's notes spent $23.81 of a $15 day before any visitor came, and Build a Trade said "Drafting is busy today" all day.
Every model call now counts in one place, by pool; a nightly-pool call is refused before it is sent when it could leave visitors
less than VISITOR_RESERVE_USD; a request's calls are the visitor pool. A draft for the same inputs on the same chain day is served
again to everyone at no cost, with this request's stock price.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.routers.thesis as thesis
from app.database import ScriptSessionLocal
from app.main import app
from app.services import ai_spend, draft_cache

pytestmark = pytest.mark.xdist_group(name="ai_spend_days")

DAY = datetime(2030, 1, 6, 15, 0, tzinfo=timezone.utc)      # a New York day no real spend touches


def test_the_nightly_may_spend_only_what_leaves_visitors_their_reserve():
    assert ai_spend.nightly_room(15.0, 0.0) == 11.0
    assert ai_spend.nightly_room(15.0, 10.5) == 0.5
    assert ai_spend.nightly_room(15.0, 23.81) == 0.0           # Nov 2: nothing more for the nightly, whatever the hour
    note = {"model": "claude-sonnet-4-6", "max_tokens": 2500, "messages": [{"role": "user", "content": "x" * 30_000}]}
    assert ai_spend.call_ceiling_usd("claude-sonnet-4-6", note) == pytest.approx(0.0675, abs=0.001)   # ~10k in at $3, 2.5k out at $15
    assert ai_spend.call_ceiling_usd("an-unpriced-model", note) is None
    assert ai_spend.pool() == ai_spend.NIGHTLY                  # outside a request: the nightly's pool


@pytest.mark.asyncio
async def test_a_nightly_call_is_refused_before_it_is_sent_and_a_visitor_call_is_not():
    request = {"model": "claude-sonnet-4-6", "max_tokens": 2500, "messages": [{"role": "user", "content": "x" * 3000}]}
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p"), {"p": "ai_spend%:2030-01-06%"})
            await s.execute(text("INSERT INTO system_metadata (key, value) VALUES ('ai_spend:2030-01-06', :v)"),
                            {"v": f"{ai_spend.cap_usd() - ai_spend.VISITOR_RESERVE_USD - 0.01:.2f}"})
            await s.commit()
            with pytest.raises(ai_spend.NightlyBudgetReached):
                await ai_spend.check_nightly(s, "claude-sonnet-4-6", request, DAY)
            token = ai_spend.set_pool(ai_spend.VISITOR)
            try:
                await ai_spend.check_nightly(s, "claude-sonnet-4-6", request, DAY)      # a visitor's feature checks the cap itself
            finally:
                ai_spend._POOL.reset(token)
            await s.execute(text("UPDATE system_metadata SET value = '1.00' WHERE key = 'ai_spend:2030-01-06'"))
            await s.commit()
            await ai_spend.check_nightly(s, "claude-sonnet-4-6", request, DAY)          # room left: the call goes ahead
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p"), {"p": "ai_spend%:2030-01-06%"})
            await s.commit()


@pytest.mark.asyncio
async def test_the_client_refuses_a_nightly_call_without_sending_it_and_counts_every_reply(monkeypatch):
    from app.services import anthropic_client
    sent: list[dict] = []
    counted: list[tuple] = []

    class FakeMessages:
        async def create(self, **kw):
            sent.append(kw)
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0,
                                                         cache_read_input_tokens=0), content=[])

    async def refuse(db, model, request, now=None):
        raise ai_spend.NightlyBudgetReached("no room")

    async def count(db, feature, cost, now=None):
        counted.append((feature, cost, ai_spend.pool()))

    client = anthropic_client.AnthropicClient.__new__(anthropic_client.AnthropicClient)
    client._client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(ai_spend, "record_call", count)
    monkeypatch.setattr(ai_spend, "check_nightly", refuse)
    with pytest.raises(ai_spend.NightlyBudgetReached):
        await client._create("generate_research_note", model="claude-sonnet-4-6", max_tokens=10, messages=[])
    assert sent == [] and counted == []
    token = ai_spend.set_pool(ai_spend.VISITOR)                 # a visitor's call is never refused here, and is counted to visitors
    try:
        await client._create("generate_thesis_draft", model="claude-fable-5", max_tokens=10, messages=[])
    finally:
        ai_spend._POOL.reset(token)
    assert len(sent) == 1 and counted == [("generate_thesis_draft", pytest.approx(0.015), "visitor")]   # 1k in at $10, 100 out at $50


@pytest.mark.asyncio
async def test_a_request_counts_against_the_visitor_pool():
    app.add_api_route("/__pool_probe", lambda: {"pool": ai_spend.pool()})
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/__pool_probe")).json() == {"pool": "visitor"}
    finally:
        app.router.routes.pop()
    assert ai_spend.pool() == ai_spend.NIGHTLY


def test_a_draft_is_kept_by_its_inputs_and_chain_day_and_served_with_this_requests_quote():
    k = draft_cache.key_for("mu", "bullish", "moderate", "2026-10-30T16:00:00-04:00", "2026-11-20", None)
    assert k == f"draft_cache:2026-10-30:MU:bullish:moderate:2026-11-20:none:v{draft_cache.DRAFT_CACHE_VERSION}"
    assert draft_cache.key_for("MU", "bullish", "moderate", "2026-10-31T16:00:00-04:00", "2026-11-20", None) != k   # the next chain
    assert draft_cache.key_for("MU", "bearish", "moderate", "2026-10-30T16:00:00-04:00", "2026-11-20", None) != k
    assert draft_cache.key_for("MU", "bullish", "aggressive", "2026-10-30T16:00:00-04:00", "2026-11-20", None) != k
    assert draft_cache.key_for("MU", "bullish", "moderate", "2026-10-30T16:00:00-04:00", "2026-11-20", 140.0) != k
    assert draft_cache.key_for("MU", "bullish", "moderate", None, "2026-11-20", None) is None        # no chain day: nothing kept
    stored = {"strategy": "Long $150 call", "fact_block": {"quote_price": 147.11, "price_as_of": "first", "quote_basis": "delayed",
                                                           "delay_minutes": 15, "atm_strike": 150}}
    served = draft_cache.restamp(stored, {"current_price": 149.004, "price_as_of": "now", "quote_basis": "close", "delay_minutes": None})
    assert served["fact_block"] == {"quote_price": 149.0, "price_as_of": "now", "quote_basis": "close", "delay_minutes": None, "atm_strike": 150}
    assert stored["fact_block"]["quote_price"] == 147.11 and served["strategy"] == "Long $150 call"


@pytest.mark.asyncio
async def test_a_kept_draft_is_served_free_even_with_the_cap_reached(monkeypatch):
    data = {"chain_last_trade": "2030-01-04T16:00:00-05:00", "chosen_exp": "2030-02-15", "current_price": 101.25,
            "price_as_of": "2030-01-06T15:00:00+00:00", "quote_basis": "delayed", "delay_minutes": 15}
    calls: list[str] = []

    async def gather(sym, db, source="manual"):
        return data

    async def nope(*a, **k):
        calls.append("charged or generated")
        raise AssertionError("a kept draft costs nothing")

    async def cap(db, now=None):
        return True

    monkeypatch.setattr(thesis, "_gather_draft_data", gather)
    monkeypatch.setattr(thesis, "_run_draft_generation", nope)
    monkeypatch.setattr(thesis, "check_draft_limit", nope)
    monkeypatch.setattr(thesis, "record_draft", nope)
    monkeypatch.setattr(ai_spend, "cap_reached", cap)
    key = draft_cache.key_for("AAPL", "bullish", "moderate", data["chain_last_trade"], data["chosen_exp"], None)
    kept = thesis.ThesisDraftRead(symbol="AAPL", direction="bullish", aggressiveness="moderate", suggested_target=110.0,
                                  suggested_strike=100.0, suggested_spread_strike=None, strategy="Long $100 call ($4.00 mid)",
                                  reasoning="r", realism_flag=None, fact_block={"quote_price": 99.0, "atm_strike": 100.0},
                                  model_used="claude-fable-5", generated_at="2030-01-06T14:00:00+00:00").model_dump()
    async with ScriptSessionLocal() as s:
        await draft_cache.put(s, key, kept, today=date(2030, 1, 6))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/theses/draft", json={"symbol": "AAPL", "direction": "bullish", "aggressiveness": "moderate"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["strategy"] == "Long $100 call ($4.00 mid)" and body["generated_at"] == "2030-01-06T14:00:00+00:00"
            assert body["fact_block"]["quote_price"] == 101.25 and body["fact_block"]["price_as_of"] == data["price_as_of"]
            # another risk level is a new draft, built by rules with no model (2026-11-06): the AI cap never closes it, only the
            # visitor's own daily draft limit can
            limited: list[str] = []

            async def limit(*a, **k):
                limited.append("limit")
                raise HTTPException(status_code=429, detail="the visitor's limit")

            monkeypatch.setattr(thesis, "check_draft_limit", limit)
            r = await c.post("/api/v1/theses/draft", json={"symbol": "AAPL", "direction": "bullish", "aggressiveness": "aggressive"})
            assert r.status_code == 429 and r.json()["detail"] == "the visitor's limit" and limited == ["limit"]
        assert calls == []
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": key})
            await s.commit()
