"""One gateway for every model call (Sam, 2026-11-16).

Nov 10 to 14: the console showed $19.91 on the production key while the ledger recorded $3.11 and the $3 cap never tripped. Every
model call this codebase makes goes through AnthropicClient._create, which checks the cap before each attempt, sends exactly one
request per attempt (the SDK's own retries are off) and records every reply; these tests fail if any module reaches the API another
way. What the gateway cannot see is the key used outside this code (Nov 10 to 14: the dev container's own nightly on the Mac).
"""
import ast
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import ai_spend, anthropic_client as G

pytestmark = pytest.mark.xdist_group(name="ai_spend_days")

APP = Path(__file__).resolve().parents[1] / "app"
GATEWAY = APP / "services" / "anthropic_client.py"
SDK_CALLS = {"create", "stream", "batches", "count_tokens"}


def _modules():
    for path in sorted(APP.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def test_no_module_but_the_gateway_imports_the_sdk_or_calls_the_api():
    found = []
    for path, tree in _modules():
        rel = path.relative_to(APP.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "anthropic" for a in node.names) and path != GATEWAY:
                found.append(f"{rel}:{node.lineno} imports anthropic")
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "anthropic" and path != GATEWAY:
                found.append(f"{rel}:{node.lineno} imports from anthropic")
            if isinstance(node, ast.Attribute) and node.attr in SDK_CALLS and isinstance(node.value, ast.Attribute) \
                    and node.value.attr in ("messages", "completions", "beta") and path != GATEWAY:
                found.append(f"{rel}:{node.lineno} calls .{node.value.attr}.{node.attr}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "/v1/messages" in node.value or "/v1/complete" in node.value:
                    found.append(f"{rel}:{node.lineno} names the model endpoint")
                if "api.anthropic.com" in node.value and path != GATEWAY:
                    found.append(f"{rel}:{node.lineno} names the API host")
    assert found == [], found


def test_every_client_method_goes_through_create_and_only_create_sends():
    tree = ast.parse(GATEWAY.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AnthropicClient")
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(methods) > 10
    for m in methods:
        uses_client = any(isinstance(n, ast.Attribute) and n.attr == "_client" for n in ast.walk(m))
        calls_create = any(isinstance(n, ast.Attribute) and n.attr == "_create" for n in ast.walk(m))
        if m.name == "__init__":
            continue
        if m.name == "_create":
            assert uses_client
        else:
            assert calls_create and not uses_client, m.name
    # nothing outside the class touches the SDK client
    outside = [n for n in tree.body if n is not cls]
    assert not any(isinstance(n, ast.Attribute) and n.attr == "_client" for o in outside for n in ast.walk(o))


def test_the_sdk_never_retries_on_its_own():
    c = G.AnthropicClient()
    assert c._client.max_retries == 0 and c._retries == 2
    assert G.AnthropicClient(max_retries=1)._retries == 1


class Fake:
    """A stand-in for the SDK's messages: replies, or raises, in turn."""

    def __init__(self, *turns):
        self.turns, self.sent = list(turns), []

    async def create(self, **kw):
        self.sent.append(kw)
        t = self.turns.pop(0)
        if isinstance(t, Exception):
            raise t
        return t


def _reply(tin=1000, tout=100):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=tin, output_tokens=tout, cache_creation_input_tokens=0,
                                                 cache_read_input_tokens=0), content=[SimpleNamespace(type="text", text="ok")])


def _client(fake, retries=2):
    c = G.AnthropicClient.__new__(G.AnthropicClient)
    c._client, c._retries = SimpleNamespace(messages=fake), retries
    return c


@pytest.fixture
def ledger(monkeypatch):
    counted, tokens, checks = [], [], []

    async def record_call(db, feature, cost, now=None):
        counted.append((feature, cost))

    async def record_tokens(db, model, tin, cw, cr, tout, now=None):
        tokens.append((model, tin, tout))

    async def check_nightly(db, model, request, now=None, skip_pause=False):
        checks.append(("nightly", skip_pause))

    async def check_visitor(db, now=None):
        checks.append(("visitor", None))

    monkeypatch.setattr(ai_spend, "record_call", record_call)
    monkeypatch.setattr(ai_spend, "record_tokens", record_tokens)
    monkeypatch.setattr(ai_spend, "check_nightly", check_nightly)
    monkeypatch.setattr(ai_spend, "check_visitor", check_visitor)
    monkeypatch.setattr(G, "RETRY_PAUSE_SECONDS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(G, "_LEDGER_BROKEN", None)
    monkeypatch.setattr(G, "_UNRECORDED", [])
    monkeypatch.setattr(G, "LEDGER_WRITE_PAUSES", (0.0, 0.0, 0.0))
    alerts = []

    async def alert(title, message, high):
        alerts.append((title, high))

    monkeypatch.setattr(G, "_alert", alert)
    return SimpleNamespace(counted=counted, tokens=tokens, checks=checks, alerts=alerts)


REQ = {"model": "claude-sonnet-4-6", "max_tokens": 300, "messages": [{"role": "user", "content": "x" * 3000}]}


@pytest.mark.asyncio
async def test_a_timed_out_attempt_is_counted_at_its_ceiling_and_the_retry_is_checked_and_counted(ledger):
    timeout = __import__("anthropic").APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    fake = Fake(timeout, _reply())
    await _client(fake)._create("read_report_date", **REQ)
    assert len(fake.sent) == 2 and ledger.checks == [("nightly", False), ("nightly", False)]
    assert ledger.counted == [("read_report_date", ai_spend.call_ceiling_usd("claude-sonnet-4-6", REQ)),
                              ("read_report_date", pytest.approx(0.0045))]          # 1k in at $3, 100 out at $15
    assert ledger.tokens == [("claude-sonnet-4-6", 1000, 100)]


@pytest.mark.asyncio
async def test_a_refused_request_is_not_retried_and_a_billing_failure_is_recorded(ledger, monkeypatch):
    failures = []

    async def record_failure(method, exc, **kw):
        failures.append(method)

    monkeypatch.setattr("app.services.ai_health.record_failure", record_failure)
    bad = __import__("anthropic").BadRequestError("credit balance is too low", response=httpx.Response(400, request=httpx.Request("POST", "https://example.invalid")), body=None)
    fake = Fake(bad, _reply())
    with pytest.raises(Exception):
        await _client(fake)._create("generate_research_note", **REQ)
    assert len(fake.sent) == 1 and ledger.counted == [] and failures == ["generate_research_note"]


@pytest.mark.asyncio
async def test_a_visitors_call_is_refused_at_the_cap_before_it_is_sent(ledger, monkeypatch):
    async def at_cap(db, now=None):
        raise ai_spend.DailyCapReached("spent")

    monkeypatch.setattr(ai_spend, "check_visitor", at_cap)
    fake = Fake(_reply())
    token = ai_spend.set_pool(ai_spend.VISITOR)
    try:
        with pytest.raises(ai_spend.DailyCapReached):
            await _client(fake)._create("generate_explain", **REQ)
    finally:
        ai_spend._POOL.reset(token)
    assert fake.sent == [] and ledger.counted == []


@pytest.mark.asyncio
async def test_a_ledger_hiccup_is_retried_and_never_trips_the_refusal(ledger, monkeypatch):
    real, fails = ai_spend.record_call, [RuntimeError("connection reset")]

    async def flaky(db, feature, cost, now=None):
        if fails:
            raise fails.pop()
        await real(db, feature, cost, now)

    monkeypatch.setattr(ai_spend, "record_call", flaky)
    fake = Fake(_reply(), _reply())
    await _client(fake)._create("read_release_eps", **REQ)
    await _client(fake)._create("read_release_eps", **REQ)
    assert len(fake.sent) == 2 and len(ledger.counted) == 2 and G._UNRECORDED == [] and ledger.alerts == []


@pytest.mark.asyncio
async def test_an_outage_refuses_calls_alerts_once_and_clears_on_its_own_with_the_spend_written(ledger, monkeypatch):
    real, down = ai_spend.record_call, [True]

    async def outage(db, feature, cost, now=None):
        if down[0]:
            raise RuntimeError("database gone")
        await real(db, feature, cost, now)

    monkeypatch.setattr(ai_spend, "record_call", outage)
    fake = Fake(_reply(), _reply())
    await _client(fake)._create("read_release_eps", **REQ)              # paid for: returned, and kept back for the ledger
    assert len(G._UNRECORDED) == 1 and ledger.alerts == [("AI spend ledger could not be written", True)]
    for _ in range(2):
        with pytest.raises(G.LedgerUnavailable):
            await _client(fake)._create("read_release_eps", **REQ)
    assert len(fake.sent) == 1 and len(ledger.alerts) == 1                # refused before sending; one alert per outage
    down[0] = False                                                       # the database answers again
    await _client(fake)._create("read_release_eps", **REQ)
    assert len(fake.sent) == 2 and G._UNRECORDED == [] and G._LEDGER_BROKEN is None
    assert [f for f, _ in ledger.counted] == ["read_release_eps", "read_release_eps"]       # the kept-back reply, then the new one
    assert ledger.alerts[-1] == ("AI spend ledger recovered", False)


@pytest.mark.asyncio
async def test_the_key_check_runs_while_paused_and_is_counted(ledger):
    fake = Fake(_reply(5, 1))
    out = await _client(fake, retries=0).key_check("claude-haiku-4-5-20251001")
    assert out["input_tokens"] == 5 and ledger.checks == [("nightly", True)] and ledger.counted[0][0] == "key_check"


@pytest.mark.asyncio
async def test_the_day_cap_refuses_a_visitor_once_spent():
    now = datetime(2030, 1, 7, 15, 0, tzinfo=timezone.utc)
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p"), {"p": "ai_spend%:2030-01-07%"})
            await s.execute(text("INSERT INTO system_metadata (key, value) VALUES ('ai_spend:2030-01-07', :v)"),
                            {"v": f"{ai_spend.cap_usd(date(2030, 1, 7)):.2f}"})
            await s.commit()
            with pytest.raises(ai_spend.DailyCapReached):
                await ai_spend.check_visitor(s, now)
            await s.execute(text("UPDATE system_metadata SET value = '0.10' WHERE key = 'ai_spend:2030-01-07'"))
            await s.commit()
            await ai_spend.check_visitor(s, now)
            await ai_spend.record_tokens(s, "claude-sonnet-4-6", 1000, 0, 0, 100, now)
            await ai_spend.record_call(s, "x", 0.0045, now)
            assert await ai_spend.tokens_by_model(s, "2030-01-07") == {"claude-sonnet-4-6": {"in": 1000, "out": 100}}
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key LIKE :p OR key LIKE :q"), {"p": "ai_spend%:2030-01-07%", "q": "ai_tokens:2030-01-07%"})
            await s.commit()
