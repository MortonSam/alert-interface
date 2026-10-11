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
        await s.execute(text("DELETE FROM system_metadata WHERE key IN (:a, :b)"), {"a": H.FAILURES_KEY, "b": H.CHECK_KEY})
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
