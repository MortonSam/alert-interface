"""Research note generation is open to visitors within limits.

Anonymous generate succeeds within the policy; the sixth in an hour and the
sixteenth in a day are 429 with a sentence naming the limit and the time it
lifts; one note per ticker per day (a second request returns today's note and
charges nothing); the owner skips the per-IP limits but not the site-wide cap;
a note reaches a visitor only after verification; a failed generation refunds
the use; PUBLIC_RESEARCH_GENERATION=false makes anonymous generate a 403.
Uses a synthetic ticker and its own rate-limit keys, removed afterwards.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.auth as auth
import app.routers.research_notes as rn
from app.database import ScriptSessionLocal
from app.main import app
from app.services.draft_limiter import RESEARCH_GENERATION_POLICY as POLICY, record_use, refund_use, global_count_today
from app.services.research_cost import estimate_cost_usd
from app.services.system_metadata_service import get_value, set_value

SYM = "ZZGEN"
IP = "203.0.113.7"
TOKEN = "test-admin-token"
ANON = {"X-Forwarded-For": IP}
ADMIN = {"X-Forwarded-For": IP, "X-Admin-Token": TOKEN}
VERIFICATION = {"claims": [], "summary": {"supported": 1, "unsupported": 0, "contradicted": 0}}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _cleanup(session) -> None:
    await session.execute(text("DELETE FROM research_notes WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
    await session.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})
    await session.execute(text("DELETE FROM system_metadata WHERE key IN (:a, :b)"),
                          {"a": f"research_gen:ip:{IP}", "b": f"research_gen:global:{_today()}"})
    await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def ticker(monkeypatch):
    monkeypatch.setattr(auth.settings, "admin_token", TOKEN)
    monkeypatch.setenv("PUBLIC_RESEARCH_GENERATION", "true")
    started: list[dict] = []

    async def fake_background(ticker_id, symbol, charge=None):
        started.append({"ticker_id": ticker_id, "symbol": symbol, "charge": charge})
    monkeypatch.setattr(rn, "run_research_note_background", fake_background)

    async with ScriptSessionLocal() as session:
        await _cleanup(session)
        await session.execute(text("""
            INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at)
            VALUES (gen_random_uuid(), :s, 'Generation test', true, now(), now())"""), {"s": SYM})
        await session.commit()
    yield started
    async with ScriptSessionLocal() as session:
        await _cleanup(session)


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _set_ip_uses(ages_minutes: list[int]) -> None:
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        await set_value(s, f"research_gen:ip:{IP}", json.dumps([(now - timedelta(minutes=m)).isoformat() for m in ages_minutes]))
        await s.commit()


async def _set_note(status: str, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    async with ScriptSessionLocal() as s:
        await s.execute(text(f"UPDATE research_notes SET status = :st{', ' + sets if sets else ''} "
                             "WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = :sym)"),
                        {"st": status, "sym": SYM, **cols})
        await s.commit()


async def _global() -> int:
    async with ScriptSessionLocal() as s:
        return await global_count_today(s, POLICY)


@pytest.mark.asyncio
async def test_anonymous_generate_within_limits_then_one_note_per_ticker_per_day(ticker):
    async with _client() as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "generating" and body["content"] == "" and body["structured_content"] is None
        assert len(ticker) == 1 and ticker[0]["charge"]["ip"] == IP and ticker[0]["charge"]["at"]
        assert await _global() == 1

        # the same ticker again: today's note comes back, nothing generated, nothing charged
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 200 and r.json()["id"] == body["id"]
        assert len(ticker) == 1 and await _global() == 1

        # a visitor reads it: status only, no text, until verification completes
        r = await c.get(f"/api/v1/research-notes?symbol={SYM}", headers=ANON)
        assert r.status_code == 200 and r.json()["content"] == "" and r.json()["verification"] is None

        await _set_note("complete", content="Revenue grew.", verification=json.dumps(VERIFICATION))
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 200 and r.json()["content"] == "Revenue grew.", "today's completed note is returned"
        assert len(ticker) == 1

        # a failed note is no note: the visitor sees a plain reason, and may generate again
        await _set_note("failed", error="RuntimeError: upstream 500 boom")
        r = await c.get(f"/api/v1/research-notes?symbol={SYM}", headers=ANON)
        assert r.json()["error"] == "Generation failed before a note was produced. Your limit was not charged."
        assert "boom" not in r.text
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 201 and len(ticker) == 2


@pytest.mark.asyncio
async def test_429_at_the_hour_and_day_limits_with_the_time_it_lifts(ticker):
    await _set_ip_uses([1, 5, 10, 20, 30])                 # five in the last hour
    async with _client() as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 429
        assert re.fullmatch(r"Note generation is limited to 5 per hour per visitor; try again after \d\d:\d\d ET", r.json()["detail"]), r.text
        assert len(ticker) == 0 and await _global() == 0

    await _set_ip_uses([90, 120, 150] + list(range(180, 180 + 12 * 60, 60)))   # fifteen today, none in the last hour
    async with _client() as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 429
        assert r.json()["detail"].startswith("Note generation is limited to 15 per day per visitor; try again after")

        # under both windows: allowed
        await _set_ip_uses([1, 5, 10, 20])
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 201


@pytest.mark.asyncio
async def test_admin_skips_the_per_ip_limit_but_not_the_site_cap(ticker):
    await _set_ip_uses([1, 5, 10, 20, 30])
    async with _client() as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ADMIN)
        assert r.status_code == 201, r.text
        assert await _global() == 1, "the owner's generation counts toward the site-wide cap"

        async with ScriptSessionLocal() as s:
            await set_value(s, f"research_gen:global:{_today()}", str(POLICY.global_day)); await s.commit()
        r = await c.post("/api/v1/research-notes/generate?force=true", json={"symbol": SYM}, headers=ADMIN)
        assert r.status_code == 429
        assert r.json()["detail"] == "Note generation has reached today's site-wide limit of 150; try again tomorrow"


@pytest.mark.asyncio
async def test_kill_switch_is_read_on_every_request(ticker, monkeypatch):
    monkeypatch.setenv("PUBLIC_RESEARCH_GENERATION", "false")
    async with _client() as c:
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        assert r.status_code == 403 and r.json()["detail"] == "Note generation is currently limited to the site owner"
        p = (await c.get("/api/v1/research-notes/policy", headers=ANON)).json()
        assert p["public"] is False and p["can_generate"] is False and p["owner_only_message"] == rn.OWNER_ONLY_MESSAGE
        p = (await c.get("/api/v1/research-notes/policy", headers=ADMIN)).json()
        assert p["can_generate"] is True
        r = await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ADMIN)
        assert r.status_code == 201, "the owner still generates"

        monkeypatch.setenv("PUBLIC_RESEARCH_GENERATION", "true")
        p = (await c.get("/api/v1/research-notes/policy", headers=ANON)).json()
        assert p["public"] is True and p["can_generate"] is True and p["owner_only_message"] is None
        assert p["per_ip_hour"] == 5 and p["per_ip_day"] == 15 and p["site_daily_cap"] == 150
        assert p["expected_wait_seconds"] == [30, 60]


@pytest.mark.asyncio
async def test_a_failed_generation_refunds_the_use(ticker):
    async with ScriptSessionLocal() as s:
        charged_at = await record_use(s, POLICY, "anon", IP, SYM)
        assert await global_count_today(s, POLICY) == 1
        assert len(json.loads(await get_value(s, f"research_gen:ip:{IP}"))) == 1
        await refund_use(s, POLICY, IP, charged_at)
        assert await global_count_today(s, POLICY) == 0
        assert json.loads(await get_value(s, f"research_gen:ip:{IP}")) == []


def test_cost_is_estimated_from_the_price_table_or_absent():
    assert estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 0) == 3.0
    assert estimate_cost_usd("claude-opus-4-6", 0, 1_000_000) == 25.0
    assert estimate_cost_usd("claude-sonnet-4-6", 12_000, 3_000) == round((12_000 * 3 + 3_000 * 15) / 1e6, 4)
    assert estimate_cost_usd("some-new-model", 10, 10) is None
    assert estimate_cost_usd("", 10, 10) is None


@pytest.mark.asyncio
async def test_health_exposes_todays_generation_count_and_spend(ticker):
    async with _client() as c:
        await c.post("/api/v1/research-notes/generate", json={"symbol": SYM}, headers=ANON)
        h = (await c.get("/health")).json()
    g = h["research_generation"]
    assert g["date"] == _today() and g["generations"] >= 1 and g["site_daily_cap"] == 150
    assert isinstance(g["estimated_spend_usd"], float) and isinstance(g["unpriced_calls"], int)
    assert g["public"] is True and g["prices_as_of"]
