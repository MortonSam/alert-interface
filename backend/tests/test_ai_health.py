"""A failed Anthropic call for billing, credit or authentication is never silent (Sep 29, 2026: a credit balance too low failed
calls with nothing on /health or in validate): recorded with its feature, an ERROR in validate, shown on /health, and caught by a
nightly key check."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import ai_health as H

pytestmark = pytest.mark.xdist_group(name="ai_api")


class FakeError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


CREDIT = FakeError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API.'}}", 400)


def test_billing_auth_and_other_failures_are_told_apart():
    assert H.classify(CREDIT) == "billing"
    assert H.classify(FakeError("invalid x-api-key", 401)) == "auth"
    assert H.classify(FakeError("permission denied for this workspace", 403)) == "auth"
    assert H.classify(FakeError("overloaded", 529)) == "other"


def test_health_shows_a_recent_billing_failure_and_the_key_check():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    failures = json.dumps([{"at": (now - timedelta(hours=2)).isoformat(), "feature": "research notes", "kind": "billing", "status": 400, "message": "credit"}])
    s = H.health_summary(failures, json.dumps({"at": now.isoformat(), "ok": True}), now)
    assert s["billing_or_auth_failure_recent"] and s["last_billing_or_auth_failure"]["feature"] == "research notes" and s["failures_last_day"] == 1
    assert not H.health_summary(failures, None, now + timedelta(hours=H.RECENT_HOURS + 1))["billing_or_auth_failure_recent"]


async def _reset():
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM system_metadata WHERE key IN (:a, :b, :c)"), {"a": H.FAILURES_KEY, "b": H.CHECK_KEY, "c": H.SERIOUS_KEY})
        await s.commit()


@pytest.mark.asyncio
async def test_every_client_call_records_its_failure_with_the_feature(monkeypatch):
    from app.services.anthropic_client import AnthropicClient
    await _reset()
    client = AnthropicClient()

    async def boom(**kwargs):
        raise CREDIT
    monkeypatch.setattr(client._client.messages, "create", boom)
    with pytest.raises(FakeError):
        await client.generate_research_note("prompt")
    with pytest.raises(FakeError):
        await client.generate_thesis_draft("prompt")
    async with ScriptSessionLocal() as s:
        from app.services.system_metadata_service import get_value
        rows = json.loads(await get_value(s, H.FAILURES_KEY))
    assert [(r["feature"], r["kind"]) for r in rows] == [("Build a Trade drafts", "billing"), ("research notes", "billing")]
    await _reset()


@pytest.mark.asyncio
async def test_validate_reports_a_billing_failure_as_an_error_the_same_night():
    from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, check_ai_api
    from app.services.system_metadata_service import set_value
    assert check_ai_api in CHECKS
    now = datetime.now(timezone.utc)
    await _reset()
    async with ScriptSessionLocal() as s:
        assert (await check_ai_api(s)).level == WARN                                   # the key check has never run
        await set_value(s, H.CHECK_KEY, json.dumps({"at": now.isoformat(), "ok": True}))
        await s.commit()
        assert (await check_ai_api(s)).level == PASS
        await set_value(s, H.FAILURES_KEY, json.dumps([{"at": now.isoformat(), "feature": "research notes", "kind": "billing", "status": 400, "message": "credit balance is too low"}]))
        await s.commit()
        r = await check_ai_api(s)
        assert r.level == ERROR and "billing" in r.message
        await set_value(s, H.CHECK_KEY, json.dumps({"at": now.isoformat(), "ok": False, "error": "auth: invalid x-api-key"}))
        await set_value(s, H.FAILURES_KEY, "[]")
        await s.commit()
        assert (await check_ai_api(s)).level == ERROR
    await _reset()


def test_the_nightly_runs_the_key_check_first_and_health_carries_it():
    from pathlib import Path
    from app.scripts.refresh import STEPS
    assert STEPS[0] == ("AI key check", ["python", "-m", "app.scripts.ai_key_check"])
    assert H.CHECK_MODEL == "claude-haiku-4-5-20251001"
    src = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert 'result["ai_api"] = redact_deep(ai_health.health_summary(' in src


# the exact error production's calls returned on 2026-10-15 (request req_011Cg3Z5srrD161LMyVkf9Fg), filed as "other" until then
USAGE_LIMIT = FakeError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your "
                        "specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC.'}, 'request_id': 'req_011Cg3Z5srrD161LMyVkf9Fg'}", 400)


def test_the_usage_limit_of_2026_10_15_is_a_billing_failure():
    assert H.classify(USAGE_LIMIT) == "billing"
    assert H.classify(FakeError("You will regain access on 2026-12-01 at 00:00 UTC.", 400)) == "billing"


def test_only_the_first_billing_failure_in_the_window_raises_the_alarm():
    now = datetime(2026, 10, 15, 7, 55, tzinfo=timezone.utc)
    old = {"at": (now - timedelta(hours=H.RECENT_HOURS + 1)).isoformat(), "kind": "billing"}
    assert H.is_first_serious([], None, now) and H.is_first_serious([old], old, now)
    assert not H.is_first_serious([{"at": (now - timedelta(minutes=1)).isoformat(), "kind": "billing"}], None, now)
    assert not H.is_first_serious([], {"at": (now - timedelta(hours=3)).isoformat(), "kind": "auth"}, now)
    assert H.is_first_serious([{"at": (now - timedelta(minutes=1)).isoformat(), "kind": "other"}], None, now)
    title, body = H.alarm_message({"kind": "billing", "feature": "nightly key check", "status": 400, "message": "usage limits"})
    assert title == "AI API billing failure" and body.startswith("nightly key check failed (status 400): usage limits")


@pytest.mark.asyncio
async def test_a_usage_limit_alarms_once_and_survives_a_burst_of_other_failures(monkeypatch):
    from app.services import notify as N
    from app.services.anthropic_client import AnthropicClient
    from app.services.system_metadata_service import get_value
    sent = []
    async def fake_notify(title, message, priority="default", tags=()):
        sent.append((title, message, priority))
        return True
    monkeypatch.setattr(N, "notify", fake_notify)
    await _reset()
    client = AnthropicClient()
    async def limit(**kwargs):
        raise USAGE_LIMIT
    monkeypatch.setattr(client._client.messages, "create", limit)
    for _ in range(3):
        with pytest.raises(FakeError):
            await client.generate_options_read("prompt")
    assert len(sent) == 1 and sent[0][0] == "AI API billing failure" and sent[0][2] == N.PRIORITY_HIGH
    assert "Ivy's Read and Ivy's pick narration failed (status 400)" in sent[0][1] and "regain access on 2026-11-01" in sent[0][1]
    for _ in range(H.KEEP + 5):                                       # a burst of other failures fills the record
        await H.record_failure("generate_explain", FakeError("overloaded", 529))
    async with ScriptSessionLocal() as s:
        failures, serious = await get_value(s, H.FAILURES_KEY), await get_value(s, H.SERIOUS_KEY)
    assert not any(f["kind"] == "billing" for f in json.loads(failures))
    summary = H.health_summary(failures, None, serious_raw=serious)
    assert summary["billing_or_auth_failure_recent"] and summary["last_billing_or_auth_failure"]["kind"] == "billing"
    assert len(sent) == 1
    await _reset()
