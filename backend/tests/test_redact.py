"""Credentials never reach a log line, a step outcome or /health; Finnhub calls are paced and 429s retried with Retry-After."""
import json

import httpx
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import finnhub_client as fc
from app.services.redact import redact, redact_deep
from app.services.step_outcomes import record_step_fields

URL = "https://finnhub.io/api/v1/stock/profile2?symbol=MU&token=d3abc123SECRET"


def test_redact_strips_every_credential_shape_and_nothing_else():
    assert redact(URL) == "https://finnhub.io/api/v1/stock/profile2?symbol=MU&token=***"
    assert redact("https://api-v2.intrinio.com/companies/MU?api_key=OjRlSECRET&x=1") == "https://api-v2.intrinio.com/companies/MU?api_key=***&x=1"
    assert redact("GET /x?apikey=abc HTTP") == "GET /x?apikey=*** HTTP" and redact("?key=abc&token=def") == "?key=***&token=***"
    assert redact("Authorization: Bearer eyJSECRET, Accept: json") == "Authorization: ***, Accept: json"
    assert redact("{'Authorization': 'Token abc'}") == "{'Authorization': '***'}"
    assert redact("{'token': 'abc', 'symbol': 'MU'}") == "{'token': '***', 'symbol': 'MU'}"
    assert redact(httpx.HTTPError(f"Client error '429 Too Many Requests' for url '{URL}'")) == "Client error '429 Too Many Requests' for url 'https://finnhub.io/api/v1/stock/profile2?symbol=MU&token=***'"
    assert redact("plain text with a token word and key=value in prose") == "plain text with a token word and key=*** in prose"
    assert redact(None) == "" and redact(42) == "42"
    assert redact_deep({"a": [URL, {"b": URL}], "n": 3}) == {"a": ["https://finnhub.io/api/v1/stock/profile2?symbol=MU&token=***", {"b": "https://finnhub.io/api/v1/stock/profile2?symbol=MU&token=***"}], "n": 3}


@pytest.mark.asyncio
async def test_a_tokened_url_never_appears_in_a_step_outcome_or_in_health():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    label = "ZZ redact test"
    try:
        await record_step_fields(label, {"error": f"Client error for url '{URL}'", "nested": {"urls": [URL]}, "exit": 1})
        async with ScriptSessionLocal() as s:
            raw = (await s.execute(text("SELECT value FROM system_metadata WHERE key = 'step_outcomes'"))).scalar()
        assert "SECRET" not in raw and "token=***" in json.dumps(json.loads(raw)[label])
        # a value stored before the redaction existed is still redacted on the way out of /health
        async with ScriptSessionLocal() as s:
            outcomes = json.loads(raw); outcomes[label]["legacy"] = URL
            await s.execute(text("UPDATE system_metadata SET value = :v WHERE key = 'step_outcomes'"), {"v": json.dumps(outcomes)})
            await s.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get("/api/v1/health")).text
            body2 = (await c.get("/health")).text if (await c.get("/health")).status_code == 200 else ""
        assert "SECRET" not in body and "SECRET" not in body2
        assert "token=***" in body
    finally:
        async with ScriptSessionLocal() as s:
            raw = (await s.execute(text("SELECT value FROM system_metadata WHERE key = 'step_outcomes'"))).scalar()
            outcomes = json.loads(raw or "{}"); outcomes.pop(label, None)
            await s.execute(text("UPDATE system_metadata SET value = :v WHERE key = 'step_outcomes'"), {"v": json.dumps(outcomes)})
            await s.commit()


def test_step_stderr_excerpts_are_redacted():
    from app.scripts.refresh import _stderr_excerpt
    head, tail = _stderr_excerpt(f"Traceback\nline two\nhttpx.HTTPStatusError: 429 for url '{URL}'")
    assert "SECRET" not in head and "token=***" in head and tail is None


def test_finnhub_pace_and_retry_after():
    assert fc.REQUESTS_PER_MINUTE == 55
    assert fc.retry_delay(None, 0) == fc.RETRY_DELAYS[0] and fc.retry_delay("1", 0) == fc.RETRY_DELAYS[0]        # never under the schedule
    assert fc.retry_delay("45", 0) == 45.0 and fc.retry_delay("bogus", 1) == fc.RETRY_DELAYS[1] and fc.retry_delay(None, 99) == fc.RETRY_DELAYS[-1]


@pytest.mark.asyncio
async def test_a_429_is_retried_and_counted_then_raised_after_the_retries(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True, "url": str(request.url)})

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr(fc.asyncio, "sleep", fake_sleep)
    async def slot(priority):                       # the shared budget has its own tests (test_finnhub_limiter); a parallel
        return True                                 # worker filling it must not turn these retries into budget waits
    monkeypatch.setattr(fc.finnhub_limiter, "acquire", slot)
    client = fc.FinnhubClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=fc.FINNHUB_BASE, params={"token": "SECRETTOKEN"})
    before = fc.finnhub_stats()
    body = await client._request("GET", "/stock/profile2", params={"symbol": "MU"})
    assert body["ok"] and calls["n"] == 2 and sleeps == [7.0]                        # Retry-After honoured
    after = fc.finnhub_stats()
    assert after["rate_limited"] == before["rate_limited"] + 1 and after["requests"] == before["requests"] + 2
    # every attempt 429: counted each time, then raised without the token
    calls["n"] = 0
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)), base_url=fc.FINNHUB_BASE, params={"token": "SECRETTOKEN"})
    with pytest.raises(fc.FinnhubRateLimited) as info:
        await client._request("GET", "/stock/profile2", params={"symbol": "MU"})
    assert "SECRETTOKEN" not in str(info.value) and fc.finnhub_stats()["retries_exhausted"] == after["retries_exhausted"] + 1
    # an HTTP error message carries no token either
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)), base_url=fc.FINNHUB_BASE, params={"token": "SECRETTOKEN"})
    with pytest.raises(httpx.HTTPStatusError) as info:
        await client._request("GET", "/stock/profile2", params={"symbol": "MU"})
    assert "SECRETTOKEN" not in str(info.value) and "token=***" in str(info.value)

# shares the step_outcomes metadata key with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="step_outcomes")
