"""An Anthropic API call that fails for billing, credit or authentication is never silent (Sep 29 to Oct 2026, a credit balance
too low failed every note, read and draft with nothing on /health or in validate).

Every call goes through AnthropicClient._create, which records a failed call here with its feature: kind "billing" (credit
balance, billing, spend limit), "auth" (an invalid or revoked key, a permission refusal) or "other". The record lives in
system_metadata (FAILURES_KEY, newest first), is logged at ERROR, shows on /health (health_summary) and makes validate's
ai_api check an ERROR the same night. The nightly also makes one tiny call (scripts/ai_key_check.py, CHECK_KEY) so a dead key
is caught before a visitor finds it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

FAILURES_KEY = "ai_api_failures"     # system_metadata: [{at, feature, kind, status, message}], newest first
CHECK_KEY = "ai_key_check"           # system_metadata: {at, ok, status, error, model}
KEEP = 50
RECENT_HOURS = 26                    # a billing or auth failure this recent is an ERROR in validate (one nightly cycle and change)
CHECK_MODEL = "claude-haiku-4-5-20251001"   # the cheapest model, a few tokens

_log = logging.getLogger("ai_api")

# what each client method serves, for the record and the alarm
FEATURES = {
    "generate_research_note": "research notes",
    "verify_research_note": "verification (research notes, Ask Ivy, Ivy's Discover sentences)",
    "generate_options_read": "Ivy's Read and Ivy's pick narration",
    "generate_explain": "metric explanations",
    "generate_thesis_draft": "Build a Trade drafts",
    "generate_thesis_draft_alternative": "Build a Trade alternative structure",
    "read_release_eps": "earnings release reader",
    "generate_answer": "Ask Ivy and Ivy's Discover sentences",
    "classify_question": "Ask Ivy's question classifier",
    "key_check": "nightly key check",
}


def classify(exc: BaseException) -> str:
    """Pure: "billing", "auth" or "other" for a failed API call."""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if any(w in text for w in ("credit balance", "billing", "spend limit", "insufficient", "quota", "payment")):
        return "billing"
    if status in (401, 403) or any(w in text for w in ("authentication", "invalid x-api-key", "invalid api key", "permission")):
        return "auth"
    return "other"


def _redacted(exc: BaseException) -> str:
    from app.services.redact import redact
    return redact(str(exc))[:300]


async def record_failure(method: str, exc: BaseException) -> dict:
    """Log the failed call at ERROR and keep it in system_metadata. Never raises."""
    entry = {"at": datetime.now(timezone.utc).isoformat(), "feature": FEATURES.get(method, method), "method": method,
             "kind": classify(exc), "status": getattr(exc, "status_code", None), "message": _redacted(exc)}
    _log.error("Anthropic API call failed: %s (%s, status %s): %s", entry["feature"], entry["kind"], entry["status"], entry["message"])
    try:
        from app.database import ScriptSessionLocal
        from app.services.system_metadata_service import get_value, set_value
        async with ScriptSessionLocal() as s:
            old = json.loads(await get_value(s, FAILURES_KEY) or "[]")
            await set_value(s, FAILURES_KEY, json.dumps([entry] + old[: KEEP - 1]))
            await s.commit()
    except Exception as e:                       # the record must never turn a failed call into a second failure
        _log.error("could not record the failed API call: %s", e)
    return entry


def health_summary(failures_raw: str | None, check_raw: str | None, now: datetime | None = None) -> dict:
    """Pure: what /health shows: the latest key check and the latest billing or auth failure, and whether one is recent."""
    now = now or datetime.now(timezone.utc)
    failures = json.loads(failures_raw or "[]")
    check = json.loads(check_raw or "null")
    serious = next((f for f in failures if f.get("kind") in ("billing", "auth")), None)
    recent = bool(serious and datetime.fromisoformat(serious["at"]) >= now - timedelta(hours=RECENT_HOURS))
    return {"key_check": check, "last_billing_or_auth_failure": serious, "billing_or_auth_failure_recent": recent,
            "failures_last_day": sum(1 for f in failures if datetime.fromisoformat(f["at"]) >= now - timedelta(hours=24))}
